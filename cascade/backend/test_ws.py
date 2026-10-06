"""P5 WebSocket 连续对话测试：模拟麦克风流式发语音，验证 VAD+EOT+ASR+LLM+TTS。"""
import asyncio
import json
import wave

import websockets


async def main():
    # 读 test.wav 的 PCM（16k Int16）
    with wave.open("../asr/test.wav", "rb") as w:
        pcm = w.readframes(w.getnframes())

    CHUNK = 1600  # 50ms @ 16kHz = 800 样本 = 1600 字节
    chunks = [pcm[i : i + CHUNK] for i in range(0, len(pcm), CHUNK)]
    silence = b"\x00\x00" * 800

    async with websockets.connect("ws://localhost:8081/ws", max_size=None) as ws:
        print("已连接，发送语音...")

        # 发语音块
        for c in chunks:
            await ws.send(c)
            await asyncio.sleep(0.01)

        # 发 1.5 秒静音触发 EOT
        for _ in range(30):
            await ws.send(silence)
            await asyncio.sleep(0.05)

        print("语音发送完，等回复...\n")

        # 收事件
        for i in range(6):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=90)
            except asyncio.TimeoutError:
                print("超时")
                break
            if isinstance(raw, (bytes, bytearray)):
                print(f"[{i}] BINARY {len(raw)}B")
            else:
                d = json.loads(raw)
                t = d.get("type")
                if t == "ai_audio":
                    print(f"[{i}] ai_audio: {len(d.get('audio',''))} 字符(base64)")
                else:
                    print(f"[{i}] {t}: {str(d.get('text', ''))[:50]}")


asyncio.run(main())
