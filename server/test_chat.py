"""发一句打招呼文本，观察完整的下行事件字段结构。"""
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
        "instructions": "你是一个温柔简洁的语音助手",
        "audio": {
            "input": {"format": {"type": "pcm", "rate": 16000}},
            "output": {"format": {"type": "pcm", "rate": 24000}, "voice": "zh_female_vv_jupiter_bigtts"},
        },
    },
}


async def main():
    async with websockets.connect(URL, additional_headers={"X-Api-Key": KEY}, max_size=None) as ws:
        await ws.send(json.dumps(SESSION_CREATE, ensure_ascii=False))
        created = json.loads(await ws.recv())
        print(f"== {created['type']}: id={created.get('session', {}).get('id')}")

        await ws.send(json.dumps({"type": "speech_text_buffer.commit", "text": "你好，请用一句话介绍你自己"}, ensure_ascii=False))
        print("== 已发送 speech_text_buffer.commit ==\n")

        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
            except asyncio.TimeoutError:
                print(f"[{i}] 超时")
                break
            if isinstance(raw, bytes):
                print(f"[{i}] BINARY {len(raw)}B")
                continue
            d = json.loads(raw)
            t = d.get("type")
            # 精简打印：type + 各字段（base64 截断）
            print(f"[{i}] type={t}")
            for k, v in d.items():
                if k == "type":
                    continue
                vs = str(v)
                print(f"      {k}: {vs[:100]}{'...(' + str(len(vs)) + ')' if len(vs) > 100 else ''}")
            if t == "response.done":
                print("\n== 一轮结束 ==")
                break


asyncio.run(main())
