"""barge-in 打断测试：AI 播放中，发同源人声（声纹匹配）验证能否打断。"""
import asyncio
import json
import wave

import websockets


async def recv_json(ws, timeout=30):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(raw, (bytes, bytearray)):
            continue
        return json.loads(raw)


async def main():
    with wave.open("../asr/test.wav", "rb") as w:
        pcm = w.readframes(w.getnframes())

    CHUNK = 1600  # 50ms @ 16kHz = 800 样本 = 1600 字节
    chunks = [pcm[i : i + CHUNK] for i in range(0, len(pcm), CHUNK)]
    silence = b"\x00\x00" * 800

    async with websockets.connect("ws://localhost:8081/ws", max_size=None) as ws:
        # 1. 发语音（注册声纹 + 触发 AI 回复）
        print("发语音（注册 + 触发回复）...")
        for c in chunks:
            await ws.send(c)
            await asyncio.sleep(0.01)
        for _ in range(30):  # 1.5s 静音 → 800ms EOT 判停
            await ws.send(silence)
            await asyncio.sleep(0.05)

        # 2. 收事件，直到 ai_audio（AI 开始播放）
        print("等 AI 回复...")
        while True:
            d = await recv_json(ws)
            print(f"  收到事件: {d['type']}")
            if d["type"] == "ai_audio":
                print("  AI 已开始播放，立即发打断语音...")
                break

        # 3. 发打断语音（500ms 人声，同源 → 声纹匹配）
        for c in chunks[:10]:
            await ws.send(c)
            await asyncio.sleep(0.05)

        # 4. 验证：收到 user_speaking（打断成功信号）
        print("等打断信号...")
        while True:
            d = await recv_json(ws, timeout=15)
            print(f"  收到事件: {d['type']}")
            if d["type"] == "user_speaking":
                print("=== 打断成功 ✅ ===")
                break


asyncio.run(main())
