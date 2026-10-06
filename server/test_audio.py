"""抓一段 TTS 音频，分析真实格式（ogg? 采样率? 声道数?）。"""
import asyncio
import base64
import json
import os
import sys

import websockets
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

KEY = os.getenv("VOLCENGINE_API_KEY", "")
URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"

SESSION_CREATE = {
    "type": "session.create",
    "session": {
        "model": "1.2.6.1",
        "instructions": "你是测试助手",
        "audio": {
            "input": {"format": {"type": "pcm", "rate": 16000}},
            "output": {"format": {"type": "pcm", "rate": 24000}, "voice": "zh_female_vv_jupiter_bigtts"},
        },
    },
}


async def main():
    audio = bytearray()
    async with websockets.connect(URL, additional_headers={"X-Api-Key": KEY}, max_size=None) as ws:
        await ws.send(json.dumps(SESSION_CREATE, ensure_ascii=False))
        await ws.recv()  # session.created
        await ws.send(json.dumps({"type": "speech_text_buffer.commit", "text": "今天天气真不错，我们一起去公园散步吧"}, ensure_ascii=False))
        for _ in range(40):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
            except asyncio.TimeoutError:
                break
            d = json.loads(raw)
            t = d.get("type")
            if t == "response.output_audio.delta":
                audio += base64.b64decode(d.get("delta", ""))
            elif t == "response.done":
                print("== response.done ==", str(d)[:200])
                break

    n = len(audio)
    print(f"\n音频字节数: {n}")
    print(f"前 16 字节 hex: {audio[:16].hex()}")
    print(f"是否 ogg_opus (OggS magic): {audio[:4] == b'OggS'}")
    print(f"字节数是否偶数(Int16对齐): {n % 2 == 0}")

    # 按 Int16 解释，看数值是否像语音 PCM
    import struct
    if n >= 2:
        samples = struct.unpack(f"<{n // 2}h", audio[: n - n % 2])
        peak = max(abs(s) for s in samples) if samples else 0
        import math
        rms = int(math.sqrt(sum(s * s for s in samples) / len(samples))) if samples else 0
        print(f"Int16 解释: 峰值={peak}, RMS={rms} (语音通常峰值 3000~32000, RMS 500~5000)")

    with open("captured_audio.pcm", "wb") as f:
        f.write(audio)
    print("已保存 captured_audio.pcm")


asyncio.run(main())
