import asyncio
import base64
import json
import os
import uuid

import httpx


async def main():
    headers = {
        "X-Api-Key": os.getenv("TTS_API_KEY", ""),
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    body = {
        "user": {"uid": "test"},
        "req_params": {
            "text": "你好，测试一下语音合成",
            "speaker": "zh_female_xiaohe_uranus_bigtts",
            "model": "seed-tts-2.0-standard",
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        },
    }
    audio = bytearray()
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        async with client.stream(
            "POST",
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
            headers=headers,
            json=body,
        ) as resp:
            print("HTTP status:", resp.status_code)
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                print("SSE:", payload[:250])
                if payload and payload != "[DONE]":
                    try:
                        d = json.loads(payload)
                        if d.get("code") in (0, 20000000) and d.get("data"):
                            audio += base64.b64decode(d["data"])
                    except Exception:
                        pass
    print("audio bytes:", len(audio))


asyncio.run(main())
