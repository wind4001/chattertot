"""打断场景测试：AI 播放中，说「小云小云，<内容>」→ 应直接回答内容（不播「在的」）。"""
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
    for i in range(0, len(pcm), 1600):
        await ws.send(pcm[i : i + 1600])
        await asyncio.sleep(0.01)
    for _ in range(30):  # 1.5s 静音 → 800ms 判停
        await ws.send(b"\x00\x00" * 800)
        await asyncio.sleep(0.05)


async def play_end(ws):
    await ws.send(json.dumps({"type": "play_end"}))
    await asyncio.sleep(0.2)


async def main():
    async with websockets.connect("ws://localhost:8081/ws", max_size=None) as ws:
        print(f"[1] {json.loads(await ws.recv())['type']}（应 idle）")

        # 唤醒（只说唤醒词）
        await send_wav(ws, f"{AUDIO}/xiaoyue_pure.wav")
        seen = []
        while "ai_text" not in seen:
            seen.append(json.loads(await ws.recv())["type"])
        print(f"[2] 唤醒: {seen}")
        await play_end(ws)

        # 让 AI 讲个长故事（便于中途打断）
        await send_wav(ws, f"{AUDIO}/verify_chat.wav")
        got_audio = False
        for _ in range(30):
            d = json.loads(await ws.recv())
            if d["type"] == "ai_text":
                print(f"[3] 故事回复: {d['text'][:30]}...")
            if d["type"] == "ai_audio":
                got_audio = True
                break
        print(f"[3] AI 开始播放: {got_audio}")

        # 播放中说「小云小云，给我讲个故事吧」
        print("[4] 播放中发 → 小云小云，给我讲个故事吧")
        await send_wav(ws, f"{AUDIO}/xiaoyun_full.wav")

        for _ in range(40):
            d = json.loads(await ws.recv())
            t = d["type"]
            if t in ("user_speaking", "asr_text", "ai_text", "wake"):
                txt = str(d.get("text", ""))[:40]
                print(f"    [{t}] {txt}")
            if t == "ai_text":
                if "在的" in d["text"]:
                    print("=== ❌ 播了「在的」（内容没被识别出来）")
                else:
                    print("=== ✅ 直接回答了内容（未播『在的』）")
                break


asyncio.run(main())
