"""状态机回归测试：覆盖 IDLE/ACTIVE/BUSY 三态与唤醒、声纹、打断、忽略逻辑。

需先启动测试服务（8081，chattertot_test 库）：
  cd cascade/backend
  DB_URL=postgresql://postgres:chattertot_dev_pw@localhost:5432/chattertot_test \
    .venv/Scripts/python.exe -m uvicorn app:app --port 8081 --ws auto

用法：python test_regression.py

注意：测试音频不在仓库里（cascade/audio-test/ 被 gitignore），需自备——
缺文件时脚本会立刻列出缺哪些，不会跑到一半才抛 FileNotFoundError。
"""
import asyncio
import json
import os
import sys
import wave

import websockets

WS_URL = "ws://localhost:8081/ws"
AUDIO = "../audio-test"

# 测试音频（KWS 把 TTS 的「小云小云」/「小月小月」都当唤醒词；后者是故意留的同音字场景）
WAKE_ONLY = f"{AUDIO}/xiaoyue_pure.wav"      # 只说唤醒词
WAKE_CONTENT = f"{AUDIO}/xiaoyun_full.wav"   # 唤醒词 + 内容（"给我讲个故事吧"）
UTTERANCE = f"{AUDIO}/verify_chat.wav"       # 普通一句话（与唤醒词同一说话人）
OTHER_SPEAKER = f"{AUDIO}/parent1.wav"       # 另一个说话人（非本轮目标）

REQUIRED_AUDIO = {
    WAKE_ONLY: "只说唤醒词（如「小云小云」）",
    WAKE_CONTENT: "唤醒词 + 内容一口气说完（如「小云小云，给我讲个故事吧」）",
    UTTERANCE: "一句较长的普通话（与唤醒词同一说话人）",
    OTHER_SPEAKER: "**另一个说话人**的录音（用于声纹过滤测试）",
}

results = []


def check_audio_or_exit():
    """缺测试音频就立刻报清楚，别跑到一半才 FileNotFoundError。"""
    missing = [p for p in REQUIRED_AUDIO if not os.path.exists(p)]
    if not missing:
        return
    print("缺测试音频（cascade/audio-test/ 不在仓库里，需自备录音）：\n")
    for p in missing:
        print(f"  ✗ {p}")
        print(f"      {REQUIRED_AUDIO[p]}")
    print(f"\n放到 {os.path.abspath(AUDIO)}/ 后重跑。")
    sys.exit(2)


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


async def recv_json(ws, timeout=40):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(raw, (bytes, bytearray)):
            continue
        return json.loads(raw)


async def send_wav(ws, path, tail_ms=1500):
    """发送音频 + 尾部静音（触发判停）。"""
    with wave.open(path, "rb") as w:
        pcm = w.readframes(w.getnframes())
    for i in range(0, len(pcm), 1600):
        await ws.send(pcm[i : i + 1600])
        await asyncio.sleep(0.005)
    silence = b"\x00\x00" * 800
    for _ in range(int(tail_ms / 50)):
        await ws.send(silence)
        await asyncio.sleep(0.05)


async def play_end(ws):
    await ws.send(json.dumps({"type": "play_end"}))
    await asyncio.sleep(0.2)


async def collect(ws, until_types, max_events=60, timeout=30):
    """收集事件直到出现 until_types 之一（或超时）。返回收到的事件类型列表。"""
    seen = []
    try:
        for _ in range(max_events):
            d = await recv_json(ws, timeout=timeout)
            seen.append(d)
            if d["type"] in until_types:
                break
    except asyncio.TimeoutError:
        pass
    return seen


def texts(events, kind):
    return [e.get("text", "") for e in events if e["type"] == kind]


async def connect():
    return await websockets.connect(WS_URL, max_size=None)


# ---------- T1: 待机 + 只说唤醒词 → 唤醒 + 回应 ----------
async def t1_wake_only():
    print("\nT1 待机 + 只说唤醒词 → 唤醒并回应")
    async with await connect() as ws:
        first = await recv_json(ws)
        check("T1.1 空闲态首事件为 idle", first["type"] == "idle", f"实际={first['type']}")
        await send_wav(ws, WAKE_ONLY)
        evs = await collect(ws, {"ai_text"}, timeout=20)
        types = [e["type"] for e in evs]
        check("T1.2 收到 wake", "wake" in types, f"事件={types}")
        ai = texts(evs, "ai_text")
        check("T1.3 有回应且为「在的」", any("在的" in t for t in ai), f"回复={ai}")
        await play_end(ws)


# ---------- T2: 待机 + 唤醒词带内容 → 直接回答（不播「在的」）----------
async def t2_wake_with_content():
    print("\nT2 待机 + 唤醒词带内容 → 直接回答")
    async with await connect() as ws:
        await recv_json(ws)
        await send_wav(ws, WAKE_CONTENT)
        evs = await collect(ws, {"ai_text"}, timeout=60)
        types = [e["type"] for e in evs]
        check("T2.1 收到 wake", "wake" in types, f"事件={types}")
        asr = texts(evs, "asr_text")
        check("T2.2 唤醒词被剥离，内容为「给我讲个故事吧」",
              any("给我讲个故事吧" == t for t in asr), f"asr={asr}")
        ai = texts(evs, "ai_text")
        check("T2.3 未播「在的」直接回答", ai and not any("在的" in t for t in ai), f"回复={ai[:1]}")
        await play_end(ws)


# ---------- T3/T4: ACTIVE 声纹确立 + 过滤非本轮说话人 ----------
async def t3_voiceprint():
    print("\nT3/T4 ACTIVE 首句确立声纹 + 过滤非本轮说话人")
    async with await connect() as ws:
        await recv_json(ws)
        await send_wav(ws, WAKE_ONLY)          # 唤醒（唤醒句确立本轮声纹）
        await collect(ws, {"ai_text"}, timeout=20)
        await play_end(ws)
        await asyncio.sleep(0.5)

        await send_wav(ws, UTTERANCE)          # 本轮说话人（同声纹）→ 应有回复
        evs = await collect(ws, {"ai_text"}, timeout=60)
        check("T3.1 本轮说话人通过声纹并回复", bool(texts(evs, "ai_text")),
              f"事件={[e['type'] for e in evs]}")
        await play_end(ws)
        await asyncio.sleep(0.5)

        await send_wav(ws, OTHER_SPEAKER)      # 非本轮说话人 → 应被过滤（无 asr_text）
        evs2 = await collect(ws, {"asr_text", "ai_text"}, max_events=25, timeout=12)
        check("T4.1 非本轮说话人被过滤", not texts(evs2, "asr_text"),
              f"事件={[e['type'] for e in evs2]}")


# ---------- T5: BUSY 打断（带内容）----------
async def t5_bargein():
    print("\nT5 播放中打断（唤醒词带内容）")
    async with await connect() as ws:
        await recv_json(ws)
        await send_wav(ws, WAKE_CONTENT)       # 唤醒 + 让 AI 讲长故事
        await collect(ws, {"ai_audio"}, timeout=90)
        await asyncio.sleep(0.5)

        await send_wav(ws, WAKE_CONTENT)       # 播放中再次"唤醒词+内容" → 打断
        evs = await collect(ws, {"ai_text"}, timeout=90, max_events=80)
        types = [e["type"] for e in evs]
        check("T5.1 触发打断", "user_speaking" in types, f"事件={types[:8]}")
        check("T5.2 打断后按内容直接回答", bool(texts(evs, "ai_text")),
              f"回复={texts(evs,'ai_text')[:1]}")


# ---------- T6: ACTIVE 只说唤醒词 → 忽略 ----------
async def t6_wake_only_in_active():
    print("\nT6 ACTIVE 中说唤醒词（无内容）→ 忽略")
    async with await connect() as ws:
        await recv_json(ws)
        await send_wav(ws, WAKE_ONLY)
        await collect(ws, {"ai_text"}, timeout=20)
        await play_end(ws)
        await asyncio.sleep(0.5)

        await send_wav(ws, WAKE_ONLY)          # 只说唤醒词 → 应忽略
        evs = await collect(ws, {"asr_text", "ai_text"}, max_events=25, timeout=12)
        check("T6.1 只有唤醒词被忽略", not texts(evs, "asr_text"),
              f"事件={[e['type'] for e in evs]}")


async def main():
    for t in (t1_wake_only, t2_wake_with_content, t3_voiceprint, t5_bargein, t6_wake_only_in_active):
        try:
            await t()
        except Exception as e:
            check(f"{t.__name__} 异常", False, f"{type(e).__name__}: {e}")

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n===== 回归结果: {passed}/{total} 通过 =====")
    for name, ok in results:
        if not ok:
            print(f"  失败: {name}")
    sys.exit(0 if passed == total else 1)


check_audio_or_exit()   # 缺音频就干净退出，不进 asyncio（否则 traceback 很吵）
asyncio.run(main())
