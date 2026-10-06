"""KWS 唤醒词全流程测试：注册（说唤醒词3次）→ 对话（声纹验证 + ASR + LLM）。"""
import asyncio
import json
import wave

import websockets

AUDIO = "../audio-test"


async def recv_json(ws, timeout=40):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(raw, (bytes, bytearray)):
            continue
        return json.loads(raw)


async def send_wav(ws, path):
    with wave.open(path, "rb") as w:
        pcm = w.readframes(w.getnframes())
    CHUNK = 1600
    for i in range(0, len(pcm), CHUNK):
        await ws.send(pcm[i : i + CHUNK])
        await asyncio.sleep(0.01)
    silence = b"\x00\x00" * 800
    for _ in range(30):  # 1.5s 静音
        await ws.send(silence)
        await asyncio.sleep(0.05)


async def main():
    async with websockets.connect("ws://localhost:8081/ws", max_size=None) as ws:
        # 1. 首次事件
        d = await recv_json(ws)
        print(f"[1] 首次事件: {d['type']}")
        assert d["type"] == "need_register", "应为 need_register"

        # 2. 注册：说「小月小月」3 次
        print("\n=== 注册阶段（说唤醒词 3 次）===")
        for i in range(3):
            await send_wav(ws, f"{AUDIO}/xiaoyue_pure.wav")
            d = await recv_json(ws)
            print(f"  第{i+1}次 → {d['type']} {d.get('count','')}")
            if d["type"] == "speaker_registered":
                print("  ✅ 注册完成")
                break
            assert d["type"] == "enroll_progress", f"应为 enroll_progress，实际 {d['type']}"

        # 3. 对话：发对话内容（同 TTS 声纹，应通过验证）
        print("\n=== 对话阶段 ===")
        await send_wav(ws, f"{AUDIO}/verify_chat.wav")
        got_asr = got_reply = False
        for _ in range(20):
            d = await recv_json(ws)
            t = d["type"]
            print(f"  [{t}] {str(d.get('text',''))[:35]}")
            if t == "asr_text":
                got_asr = True
            if t == "ai_text":
                got_reply = True
                break

        if got_asr and got_reply:
            print("\n=== 全流程通过 ✅ ===")
        else:
            print(f"\n=== 失败（asr={got_asr} reply={got_reply}）===")


asyncio.run(main())
