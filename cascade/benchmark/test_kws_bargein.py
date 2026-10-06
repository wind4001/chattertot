"""KWS 打断测试：AI 播放中，说唤醒词「小月小月」打断。"""
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
    for _ in range(30):
        await ws.send(silence)
        await asyncio.sleep(0.05)


async def main():
    async with websockets.connect("ws://localhost:8081/ws", max_size=None) as ws:
        d = await recv_json(ws)
        print(f"[1] {d['type']}（DB 有声纹，应为 idle）")
        assert d["type"] == "idle"

        await send_wav(ws, f"{AUDIO}/xiaoyue_pure.wav")
        d = await recv_json(ws)
        print(f"[2] {d['type']}（唤醒）")
        assert d["type"] == "wake"

        await send_wav(ws, f"{AUDIO}/verify_chat.wav")
        while True:
            d = await recv_json(ws)
            print(f"[3] {d['type']}")
            if d["type"] == "ai_audio":
                print("AI 播放中，发唤醒词打断...")
                break

        await send_wav(ws, f"{AUDIO}/xiaoyue_pure.wav")
        while True:
            d = await recv_json(ws)
            print(f"[4] {d['type']}")
            if d["type"] == "user_speaking":
                print("=== 打断成功 ✅ ===")
                break


asyncio.run(main())
