"""P5 后端：WebSocket 连续对话（VAD + EOT）+ 原 /transcribe 接口。"""
import array
import asyncio
import base64
import io
import json
import math
import os
import pathlib
import re
import time
import wave

import httpx
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import db
import llm
import tts

app = FastAPI(title="Cascade Backend")

ASR_URL = "http://localhost:8000/v1/audio/transcriptions"

# VAD 参数（可调）
SPEECH_THRESHOLD = 300  # RMS 阈值（int16），低于视为静音


def rms_int16(pcm: bytes) -> int:
    if len(pcm) < 2:
        return 0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not samples:
        return 0
    return int((sum(s * s for s in samples) / len(samples)) ** 0.5)


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


SPEAKER_URL = "http://localhost:8001/embedding"
SPEAKER_THRESHOLD = 0.5  # 余弦相似度阈值，低于视为非当前说话人（实测：孩子 0.745 / 家长 0.16~0.36）

# EOT 判停参数
EOT_MS = 800  # 静音判停阈值（固定；埋点采集真实停顿时长后，v1.x 再上自适应）
MAX_AUDIO_BYTES = 32000 * 10  # 音频最大缓存 10s（16kHz 16bit = 32000 B/s）
IDLE_TIMEOUT_MS = 30000  # 活跃态静默超时（从客户端播完 AI 语音起算），超时回待机
VOICE_MIN_BYTES = 48000  # 确立本轮目标声纹所需的最短音频（1.5s；再短声纹不可靠）
DEBUG_AUDIO = os.getenv("DEBUG_AUDIO", "0") == "1"  # 调试音频落盘开关（默认关，避免无界累积）


# 唤醒词「小云小云」的剥离：先精确匹配，再容忍 ASR 同音字误听（云→月/运/韵/允）
_WAKE_EXACT_RE = re.compile(r"^[，,。.、\s]*小\s*云\s*小\s*云[，,。.！!？?、\s]*")
_WAKE_LOOSE_RE = re.compile(r"^[，,。.、\s]*[小晓][云月运韵允][小晓][云月运韵允][，,。.！!？?、\s]*")


def strip_wake_word(text: str) -> str:
    """剥掉句首唤醒词及其前后的标点空格，返回剩余内容。

    先精确匹配「小云小云」；KWS 已确认句首是唤醒词，但 ASR 可能听成同音字
    （如「小月小月」），故再放宽匹配一次。返回空串表示"只有唤醒词、无内容"。
    """
    t = text.strip()
    for pat in (_WAKE_EXACT_RE, _WAKE_LOOSE_RE):
        s = pat.sub("", t).strip()
        if s != t:
            return s
    return t

# KWS 唤醒词检测服务（FunASR SANM，句末检测「小云小云」）
KWS_URL = "http://localhost:8002/detect"

MEMORY_SCOPE = "default"  # 长期记忆归属（阶段 3 引入声纹档案后改为 speaker_id）
MIN_SUMMARIZE_MSGS = 4  # 少于这么多条新消息就不值得摘要
_summarize_lock = asyncio.Lock()  # 防多连接并发摘要


async def summarize_session():
    """会话结束：把新增消息摘要进长期记忆档案（幂等，靠水位线）。"""
    async with _summarize_lock:
        try:
            prof = await db.get_profile(MEMORY_SCOPE)
            msgs = await db.get_messages_since(prof["last_message_id"])
            if len(msgs) < MIN_SUMMARIZE_MSGS:
                return
            convo = "\n".join(
                f"{'小朋友' if m['role'] == 'user' else '小云'}：{m['content']}" for m in msgs
            )
            facts = await llm.summarize(convo, prof["facts"])
            if facts:
                await db.update_profile(MEMORY_SCOPE, facts, msgs[-1]["id"])
                print(f"[MEM] 长期记忆已更新：{len(msgs)} 条消息 → {len(facts)} 字", flush=True)
        except Exception as e:
            print(f"[MEM] 摘要失败: {type(e).__name__}: {e}", flush=True)


async def extract_embedding(wav: bytes) -> list:
    """调声纹服务提取 192 维声纹向量。"""
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.post(SPEAKER_URL, files={"file": ("audio.wav", wav, "audio/wav")})
    resp.raise_for_status()
    return resp.json()["embedding"]


async def kws_detect(wav: bytes) -> dict:
    """调 FunASR KWS 服务检测唤醒词「小云小云」，返回 {detected, score, text}。"""
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(KWS_URL, files={"file": ("audio.wav", wav, "audio/wav")})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[KWS] 检测失败: {e}", flush=True)
        return {"detected": False, "score": 0.0, "text": ""}


def save_debug_wav(pcm: bytes, tag: str) -> str:
    """保存调试音频（定位识别/声纹问题用）。仅当 DEBUG_AUDIO=1 时落盘。"""
    if not DEBUG_AUDIO:
        return ""
    try:
        _dbg = pathlib.Path(__file__).parent / "debug_audio"
        _dbg.mkdir(exist_ok=True)
        _p = _dbg / f"{tag}_{int(time.time() * 1000)}.wav"
        _p.write_bytes(pcm_to_wav(pcm))
        return _p.name
    except Exception:
        return ""


def cosine_similarity(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def asr_text(wav: bytes) -> str:
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        resp = await client.post(
            ASR_URL,
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"model": "sensevoice", "response_format": "verbose_json", "language": "zh"},
        )
    resp.raise_for_status()
    return resp.json().get("text", "")


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    data = await file.read()
    text = await asr_text(data)
    reply = await llm.chat(text) if text else None
    if reply is None:
        reply = "刚刚我没听清，你再说一遍好吗？"
    audio_bytes = await tts.synthesize(reply) if reply else b""
    return {
        "text": text,
        "reply": reply,
        "audio": base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else "",
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    state = "IDLE"  # IDLE（待机）| ACTIVE（活跃对话）
    speech = bytearray()
    is_speaking = False
    silence_ms = 0
    busy = False  # AI 播放中（含客户端播放期，直到 play_end / 兜底超时）
    cancelable_task = None  # 当前可被唤醒词打断取消的任务（对话轮次 / 打断回应播放）
    idle_ms = 0  # ACTIVE 静默计时（客户端播完 AI 语音后才开始累计）
    seq = 0  # 轮次序号：用于判定"我这一轮是否已被打断/被新轮次取代"
    play_rms_sum = 0  # 诊断：播放期间麦克风能量累计
    play_rms_n = 0
    play_rms_max = 0
    reference_embedding = None  # 本轮目标声纹（唤醒句或唤醒后首句确立，轮次结束释放）

    # 无全局注册：每轮对话自成声纹
    await ws.send_json({"type": "idle"})

    async def play_reply_and_wait(reply: str, my_turn: int):
        """播放回复；等客户端播完（play_end）或兜底超时，之后才开始计静默。"""
        nonlocal busy, idle_ms
        total = 0
        await ws.send_json({"type": "ai_text", "text": reply})
        async for pcm_chunk in tts.synthesize_stream(reply):
            total += len(pcm_chunk)
            await ws.send_json({
                "type": "ai_audio",
                "audio": base64.b64encode(pcm_chunk).decode("ascii"),
                "sample_rate": 24000,
            })
        wait_s = total / 48000 + 1.0  # 24kHz 16bit = 48000 B/s，+1s 余量
        print(f"[TTS] 发完 {total/48000:.1f}s 音频，等客户端播完", flush=True)
        await asyncio.sleep(wait_s)
        if seq == my_turn:  # play_end 没来，兜底
            print("[播放] 兜底超时（未收到 play_end）", flush=True)
            busy = False
            idle_ms = 0

    async def process_turn(speech_bytes: bytes, text_override=None):
        """ACTIVE：确立/验证本轮声纹 → ASR → LLM → TTS。"""
        nonlocal busy, idle_ms, reference_embedding, seq
        seq += 1
        my_turn = seq
        busy = True  # 本轮处理中：禁止并发轮次（唤醒/打断路径直接调用时也要置位）
        try:
            wav = pcm_to_wav(speech_bytes)
            if text_override is None:
                if len(speech_bytes) < 3200:  # <100ms，太短忽略
                    return
                # 本轮声纹未确立 → 用这句长话确立；已确立 → 验证过滤
                if reference_embedding is None:
                    if len(speech_bytes) >= VOICE_MIN_BYTES:
                        try:
                            reference_embedding = await extract_embedding(wav)
                            print(f"[声纹] 本轮目标声纹确立 来源=首句 {len(speech_bytes)/32000:.1f}s", flush=True)
                        except Exception as e:
                            print(f"[声纹] 提取失败: {e}", flush=True)
                else:
                    try:
                        emb = await extract_embedding(wav)
                        sim = cosine_similarity(reference_embedding, emb)
                        if sim < SPEAKER_THRESHOLD:
                            print(f"[声纹] 非本轮说话人 相似度={sim:.3f}，忽略", flush=True)
                            return
                    except Exception as e:
                        print(f"[声纹] 验证失败: {e}，放行", flush=True)
                text = await asr_text(wav)
            else:
                text = text_override
            name = save_debug_wav(speech_bytes, "turn")
            print(f"[TURN] 音频={len(speech_bytes)/32000:.2f}s 识别={text!r} 存={name}", flush=True)
            if not text:
                return
            # 对话中只说唤醒词（无内容）→ 不当成问题，忽略
            if not strip_wake_word(text):
                print(f"[轮次] 只有唤醒词 {text!r}，忽略", flush=True)
                return
            await ws.send_json({"type": "asr_text", "text": text})
            history = []
            facts = ""
            try:
                history = await db.get_recent_messages(20)
                facts = (await db.get_profile())["facts"]  # 长期记忆档案（每轮取最新）
            except Exception:
                pass
            print(f"[MEM] 上下文 历史={len(history)}条 长期记忆={len(facts)}字", flush=True)
            reply = await llm.chat(text, history, facts)
            if reply is None:
                print("[LLM] 熔断降级，播兜底话术", flush=True)
                reply = "刚刚我没听清，你再说一遍好吗？"
            else:
                try:
                    await db.add_message("user", text)
                    await db.add_message("assistant", reply)
                except Exception:
                    pass
            await play_reply_and_wait(reply, my_turn)
        except asyncio.CancelledError:
            raise  # 打断方已处理 busy，不在这里复位
        except Exception as e:
            print(f"[P5] process_turn error: {type(e).__name__}: {e}", flush=True)
        finally:
            if seq == my_turn:  # 本轮未被取代/打断 → 复位
                busy = False
                idle_ms = 0

    async def detect_wake(speech_bytes: bytes):
        """IDLE：KWS 检测唤醒词。命中即唤醒；若同句还说了内容，直接当第一轮处理。"""
        nonlocal state, busy, idle_ms, reference_embedding, seq
        seq += 1
        my_turn = seq
        try:
            if len(speech_bytes) < 3200:
                return
            wav = pcm_to_wav(speech_bytes)
            kw = await kws_detect(wav)
            if not kw.get("detected"):
                return  # 非唤醒词，继续待机
            state = "ACTIVE"
            print(f"[唤醒] 命中 音频={len(speech_bytes)/32000:.2f}s", flush=True)
            await ws.send_json({"type": "wake"})
            # 唤醒句够长 → 直接确立本轮目标声纹
            if len(speech_bytes) >= VOICE_MIN_BYTES:
                try:
                    reference_embedding = await extract_embedding(wav)
                    print("[声纹] 本轮目标声纹确立 来源=唤醒句", flush=True)
                except Exception as e:
                    print(f"[声纹] 提取失败: {e}", flush=True)
            # 同一句里是否还说了别的内容（例："小云小云，给我讲个故事吧"）
            content = strip_wake_word(await asr_text(wav))
            if content:
                # 唤醒句里已经带了问题 → 直接回答，不要先说「我在呢」（中间空档会让孩子以为没听到而重复）
                print(f"[唤醒] 同句含内容: {content!r} → 直接回答", flush=True)
                await process_turn(speech_bytes, text_override=content)
            else:
                await play_reply_and_wait("在的，你说～", my_turn)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[KWS] 唤醒失败: {e}", flush=True)
        finally:
            if seq == my_turn:
                busy = False
                idle_ms = 0

    async def detect_bargein(speech_bytes: bytes):
        """BUSY：判停后 KWS 检测，命中「小云小云」打断。"""
        nonlocal busy, is_speaking, speech, silence_ms, idle_ms, seq, cancelable_task
        try:
            if len(speech_bytes) < 3200:
                return
            kw = await kws_detect(pcm_to_wav(speech_bytes))
            name = save_debug_wav(speech_bytes, "bargein")
            print(f"[BARGEIN] 音频={len(speech_bytes)/32000:.2f}s kws={kw} 存={name}", flush=True)
            if kw.get("detected"):
                seq += 1  # 让被取消的旧任务的 finally 不再复位 busy
                if cancelable_task and not cancelable_task.done():
                    cancelable_task.cancel()
                busy = False
                is_speaking = False
                speech = bytearray()
                silence_ms = 0
                idle_ms = 0
                print("[KWS] 唤醒词打断", flush=True)
                await ws.send_json({"type": "user_speaking"})
                cancelable_task = asyncio.current_task()
                busy = True
                # 打断句里是否还说了内容（例："小云小云，为什么天是蓝的"）→ 直接回答
                content = strip_wake_word(await asr_text(pcm_to_wav(speech_bytes)))
                if content:
                    print(f"[打断] 同句含内容: {content!r}", flush=True)
                    await process_turn(speech_bytes, text_override=content)
                    return
                # 只说了唤醒词 → 播一句短回应，再进入聆听
                seq += 1
                await play_reply_and_wait("在的，你说～", seq)
            # 非唤醒词：不打断，AI 继续播（busy 保持 True）
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[KWS] 打断失败: {e}", flush=True)

    def finalize_turn(reason: str):
        """判停：按状态分发（待机唤醒检测 / 播放中打断检测 / 对话）。"""
        nonlocal is_speaking, speech, silence_ms, busy, cancelable_task, state
        turn = bytes(speech)
        was_busy = busy
        is_speaking = False
        speech = bytearray()
        silence_ms = 0
        busy = True
        print(f"[EOT] {reason} 音频={len(turn)/32000:.2f}s", flush=True)
        if state == "IDLE":
            asyncio.create_task(detect_wake(turn))
        elif was_busy:
            asyncio.create_task(detect_bargein(turn))
        else:
            cancelable_task = asyncio.create_task(process_turn(turn))

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "text" in msg:  # 客户端控制消息（play_end：本段 AI 语音播放完毕）
                try:
                    d = json.loads(msg["text"])
                except Exception:
                    continue
                if d.get("type") == "play_end":
                    seq += 1
                    busy = False
                    idle_ms = 0
                    print("[播放] 客户端播完，开始计静默", flush=True)
                continue
            if "bytes" not in msg:
                continue
            pcm = msg["bytes"]
            rms = rms_int16(pcm)

            # 诊断：播放期间统计麦克风能量（判断 AEC 是否把回声压住了）
            if busy:
                play_rms_sum += rms
                play_rms_n += 1
                if rms > play_rms_max:
                    play_rms_max = rms
                if play_rms_n >= 40:  # 约 2 秒
                    avg = play_rms_sum / play_rms_n
                    print(f"[ECHO] 播放期间麦克风能量 均值={avg:.0f} 峰值={play_rms_max}（阈值{SPEECH_THRESHOLD}）", flush=True)
                    play_rms_sum = 0
                    play_rms_n = 0
                    play_rms_max = 0

            # 所有状态都做 VAD（检测说话 + 判停）
            if rms > SPEECH_THRESHOLD:
                if not is_speaking:
                    is_speaking = True
                    if state == "ACTIVE" and not busy:
                        await ws.send_json({"type": "user_speaking"})
                speech.extend(pcm)
                silence_ms = 0
                if len(speech) >= MAX_AUDIO_BYTES:
                    finalize_turn("音频达缓存上限")
            else:
                if is_speaking:
                    speech.extend(pcm)
                    silence_ms += len(pcm) / 32000 * 1000
                    if silence_ms >= EOT_MS or len(speech) >= MAX_AUDIO_BYTES:
                        finalize_turn(f"静音判停 静音={silence_ms:.0f}ms")
                else:
                    # 静默（仅 ACTIVE 且不在播放 → 计时回待机）
                    if state == "ACTIVE" and not busy:
                        idle_ms += len(pcm) / 32000 * 1000
                        if idle_ms >= IDLE_TIMEOUT_MS:
                            state = "IDLE"
                            reference_embedding = None  # 本轮结束，释放声纹
                            idle_ms = 0
                            print("[IDLE] 静默超时，回待机（本轮声纹已释放）", flush=True)
                            await ws.send_json({"type": "idle"})
                            asyncio.create_task(summarize_session())  # 本轮会话结束 → 更新长期记忆
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] 主循环异常: {e}", flush=True)
    finally:
        asyncio.create_task(summarize_session())  # 连接断开 → 更新长期记忆


STATIC_DIR = pathlib.Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, ws="auto")
