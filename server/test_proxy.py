"""端到端代理测试：连本机 /ws，走一遍 start_session + text_query，观察转发结果。"""
import asyncio
import json
import sys

import websockets

sys.stdout.reconfigure(encoding="utf-8")


async def main():
    async with websockets.connect("ws://localhost:30013/ws", max_size=None) as ws:
        ready = json.loads(await ws.recv())
        print(f"== 后端: {ready}")

        await ws.send(json.dumps({
            "type": "start_session",
            "config": {"voice": "zh_female_vv_jupiter_bigtts", "system_prompt": "你是测试助手"},
        }, ensure_ascii=False))
        print("已发送 start_session")

        await ws.send(json.dumps({
            "type": "text_query",
            "content": "你好，请用一句话介绍你自己",
        }, ensure_ascii=False))
        print("已发送 text_query\n")

        audio_bytes = 0
        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
            except asyncio.TimeoutError:
                print(f"[{i}] 超时")
                break
            if isinstance(raw, (bytes, bytearray)):
                audio_bytes += len(raw)
                if audio_bytes < 4000:
                    print(f"[{i}] BINARY {len(raw)}B")
                continue
            d = json.loads(raw)
            print(f"[{i}] {d.get('type')}: {str(d)[:140]}")
            if d.get("type") == "chat_ended":
                break
        print(f"\n== 共收到 {audio_bytes} 字节音频 ==")


asyncio.run(main())
