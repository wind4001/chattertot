"""协议冒烟脚本共用的轮次跟踪与播放确认。"""
import asyncio
import json


def track_event(ws, event):
    if event["type"] == "turn_start":
        ws._lym_turn_id = event["turn_id"]
        ws._lym_audio_ended = False
    elif event["type"] == "audio_end" and event["turn_id"] == getattr(ws, "_lym_turn_id", None):
        ws._lym_audio_ended = True
    return event


async def acknowledge_playback(ws, receive):
    # 脚本不播放声音，但也必须等本轮发送结束，不能在 ai_text 到达时提前确认。
    async with asyncio.timeout(120):
        while not getattr(ws, "_lym_audio_ended", False):
            await receive(ws)
    await ws.send(json.dumps({"type": "play_end", "turn_id": ws._lym_turn_id}))
    await asyncio.sleep(0.2)
