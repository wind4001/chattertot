"""注册 + 第二段验证测试：确认注册后声纹验证能通过、正常回复。"""
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


async def send_audio(ws, chunks, silence):
    for c in chunks:
        await ws.send(c)
        await asyncio.sleep(0.01)
    for _ in range(30):  # 1.5s 静音触发判停
        await ws.send(silence)
        await asyncio.sleep(0.05)


async def main():
    with wave.open("../asr/test.wav", "rb") as w:
        pcm = w.readframes(w.getnframes())
    CHUNK = 1600
    chunks = [pcm[i : i + CHUNK] for i in range(0, len(pcm), CHUNK)]
    silence = b"\x00\x00" * 800

    async with websockets.connect("ws://localhost:8081/ws", max_size=None) as ws:
        # 第一段：注册
        print("发第一段语音（注册）...")
        await send_audio(ws, chunks, silence)

        reg_ok = False
        for _ in range(20):
            d = await recv_json(ws)
            t = d["type"]
            print(f"  [{t}] {str(d.get('text', ''))[:30]}")
            if t == "speaker_registered":
                reg_ok = True
            if t == "ai_audio":
                break  # 第一段回复开始播
        if not reg_ok:
            print("=== 注册失败 ===")
            return

        # 等第一段回复播完（第一段 TTS 可能较长，等足够久）
        await asyncio.sleep(12)

        # 第二段：验证声纹 + 回复
        print("发第二段语音（验证）...")
        await send_audio(ws, chunks, silence)

        got_asr = got_reply = False
        for _ in range(60):
            d = await recv_json(ws)
            t = d["type"]
            print(f"  [{t}] {str(d.get('text', ''))[:30]}")
            if t == "asr_text":
                got_asr = True
            if t == "ai_text":
                got_reply = True
                break

        if got_asr and got_reply:
            print("=== 注册 + 第二段验证通过 ✅ ===")
        else:
            print(f"=== 失败（asr={got_asr} reply={got_reply}）===")


asyncio.run(main())
