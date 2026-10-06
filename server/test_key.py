"""测试新版控制台 X-Api-Key + session.create 握手。"""
import asyncio
import json
import os
import sys

import websockets

sys.stdout.reconfigure(encoding="utf-8")

KEY = os.getenv("TTS_API_KEY", "")
URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"

SESSION_CREATE = {
    "type": "session.create",
    "session": {
        "model": "1.2.6.1",
        "instructions": "你是一个测试助手",
        "audio": {
            "input": {"format": {"type": "pcm", "rate": 16000}},
            "output": {"format": {"type": "pcm", "rate": 24000}, "voice": "zh_female_vv_jupiter_bigtts"},
        },
    },
}


async def main():
    try:
        async with websockets.connect(URL, additional_headers={"X-Api-Key": KEY}, max_size=None) as ws:
            print("WS 连接成功（鉴权通过）")
            await ws.send(json.dumps(SESSION_CREATE, ensure_ascii=False))
            print("已发送 session.create，等待响应...\n")

            for i in range(3):
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=15)
                    if isinstance(resp, bytes):
                        print(f"[{i+1}] (binary {len(resp)} 字节): {resp[:80]!r}")
                    else:
                        print(f"[{i+1}] (text): {resp[:600]}")
                except asyncio.TimeoutError:
                    print(f"[{i+1}] 等待响应超时")
                    break
    except Exception as e:
        print(f"连接失败: {type(e).__name__}: {e}")


asyncio.run(main())
