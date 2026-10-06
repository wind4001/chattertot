"""每轮声纹方案测试：唤醒 → 首句确立声纹 → 后续对话验证 → play_end 计时。

测试点：
1. 只说「小云小云」→ 唤醒
2. 唤醒后首句（长话）→ 确立本轮声纹 + 正常回复
3. 再来一句 → 声纹验证通过 + 回复
4. play_end 被正确处理（服务端日志可见"客户端播完"）
"""
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


async def send_wav(ws, path, eot=True):
    with wave.open(path, "rb") as w:
        pcm = w.readframes(w.getnframes())
    CHUNK = 1600
    for i in range(0, len(pcm), CHUNK):
        await ws.send(pcm[i : i + CHUNK])
        await asyncio.sleep(0.01)
    if eot:
        silence = b"\x00\x00" * 800
        for _ in range(30):  # 1.5s 静音 → 800ms 判停
            await ws.send(silence)
            await asyncio.sleep(0.05)


async def play_end(ws):
    await ws.send(json.dumps({"type": "play_end"}))
    await asyncio.sleep(0.2)


async def drain_until(ws, want, limit=25):
    """收事件直到出现 want（或收满 limit 个）。返回收到的类型列表。"""
    seen = []
    for _ in range(limit):
        d = await recv_json(ws)
        seen.append(d["type"])
        if d["type"] == "ai_text":
            print(f"     ai_text: {d['text'][:35]}")
        if d["type"] in want:
            return seen
    return seen


async def main():
    async with websockets.connect("ws://localhost:8081/ws", max_size=None) as ws:
        d = await recv_json(ws)
        print(f"[1] 首事件: {d['type']}（应 idle）")

        # --- 只说唤醒词 ---
        await send_wav(ws, f"{AUDIO}/xiaoyue_pure.wav")  # TTS 的「小月小月」，KWS 判为小云
        seen = await drain_until(ws, {"ai_text"})
        print(f"    事件: {seen}  → 唤醒{'成功' if 'wake' in seen else '失败'}")
        await play_end(ws)

        # --- 唤醒后首句（长话，确立本轮声纹）---
        await send_wav(ws, f"{AUDIO}/verify_chat.wav")
        seen = await drain_until(ws, {"ai_text"})
        print(f"[3] 首句: {seen}")
        await play_end(ws)

        # --- 再来一句（声纹验证）---
        await send_wav(ws, f"{AUDIO}/verify_chat.wav")
        seen = await drain_until(ws, {"ai_text"})
        print(f"[4] 第二句: {seen}")


asyncio.run(main())
