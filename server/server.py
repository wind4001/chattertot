"""
M1 后端代理：客户端 <-> 火山引擎 realtime/dialogue（新版全双工 JSON 协议）

客户端 <-> 后端：JSON 控制 + 原始 PCM 二进制（上行音频）
后端 <-> 火山：JSON 文本帧（音频 base64 编码）
"""
import asyncio
import base64
import json
import logging
import os
import pathlib

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s")
logger = logging.getLogger("lym-sound")

VOLCENGINE_WS_URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
PORT = int(os.getenv("PORT", 30013))
MODEL = "1.2.6.1"
DEFAULT_VOICE = "zh_female_vv_jupiter_bigtts"

PUBLIC_DIR = pathlib.Path(__file__).parent / "public"

app = FastAPI(title="Lym Sound M1")


@app.websocket("/ws")
async def ws_endpoint(browser_ws: WebSocket):
    await browser_ws.accept()
    logger.info("客户端 WebSocket 已连接")

    state = {"session_id": None, "active": False}
    volc_ws = None

    try:
        volc_ws = await _connect()
        await browser_ws.send_json({"type": "ready"})

        up = asyncio.create_task(_upstream(browser_ws, volc_ws, state))
        down = asyncio.create_task(_downstream(browser_ws, volc_ws, state))

        done, pending = await asyncio.wait([up, down], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            exc = t.exception()
            if exc is None:
                continue
            if isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)):
                logger.info("任务因对端关闭结束: %r", exc)
            else:
                logger.error("任务异常: %r", exc, exc_info=exc)
    except Exception as e:
        logger.exception("ws_endpoint error")
        try:
            await browser_ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        await _cleanup(volc_ws)
        logger.info("会话清理完成")


async def _connect():
    ws = await websockets.connect(VOLCENGINE_WS_URL, additional_headers={"X-Api-Key": API_KEY}, max_size=None)
    logger.info("火山连接已建立")
    return ws


async def _cleanup(volc_ws):
    if volc_ws is None:
        return
    try:
        await volc_ws.send(json.dumps({"type": "session.close"}, ensure_ascii=False))
        await volc_ws.close()
    except Exception:
        pass


def _build_session_create(config: dict) -> dict:
    model = config.get("model", MODEL)
    voice = config.get("voice", DEFAULT_VOICE)
    instructions = config.get("system_prompt") or config.get("instructions") or ""

    session = {
        "model": model,
        "instructions": instructions,
        "audio": {
            "input": {"format": {"type": "pcm", "rate": 16000}},
            "output": {"format": {"type": "pcm", "rate": 24000}, "voice": voice},
        },
    }
    if config.get("speed") is not None:
        session["audio"]["output"]["speed"] = int(config["speed"])
    if config.get("loudness") is not None:
        session["audio"]["output"]["loudness"] = int(config["loudness"])

    return {"type": "session.create", "session": session}


# ---------- 上行：客户端 -> 火山 ----------
async def _upstream(browser_ws: WebSocket, volc_ws, state):
    try:
        while True:
            msg = await browser_ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "text" in msg:
                data = json.loads(msg["text"])
                await _handle_text(data, volc_ws, state)
            elif "bytes" in msg and msg["bytes"]:
                if state["active"]:
                    b64 = base64.b64encode(msg["bytes"]).decode("ascii")
                    await volc_ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": b64}))
    except WebSocketDisconnect:
        logger.info("客户端断开（上行）")
    except asyncio.CancelledError:
        pass


async def _handle_text(data: dict, volc_ws, state):
    t = data.get("type")

    if t == "start_session":
        await volc_ws.send(json.dumps(_build_session_create(data.get("config", {})), ensure_ascii=False))
        logger.info("session.create 已发送")

    elif t == "stop_session":
        await volc_ws.send(json.dumps({"type": "session.close"}, ensure_ascii=False))
        logger.info("session.close 已发送")

    elif t == "text_query":
        # 用打招呼事件让模型直接合成文本回复
        await volc_ws.send(json.dumps({"type": "speech_text_buffer.commit", "text": data.get("content", "")}, ensure_ascii=False))

    elif t == "interrupt":
        # 客户端打断
        await volc_ws.send(json.dumps({"type": "response.cancel"}, ensure_ascii=False))


# ---------- 下行：火山 -> 客户端 ----------
async def _downstream(browser_ws: WebSocket, volc_ws, state):
    try:
        async for raw in volc_ws:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="replace")
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _relay(d, browser_ws, state)
    except websockets.exceptions.ConnectionClosed:
        logger.info("火山连接关闭（下行）")
    except WebSocketDisconnect:
        logger.info("客户端断开（下行）")
    except asyncio.CancelledError:
        pass


async def _relay(d: dict, ws: WebSocket, state):
    t = d.get("type")
    # 音频 delta 太频繁，其余事件都记一行，方便定位
    if t != "response.output_audio.delta":
        logger.info("下行事件: %s", t)

    if t == "session.created":
        state["active"] = True
        state["session_id"] = d.get("session", {}).get("id", "")
        await ws.send_json({"type": "session_started", "dialog_id": state["session_id"]})

    elif t == "session.closed":
        state["active"] = False
        await ws.send_json({"type": "session_finished"})

    elif t == "conversation.item.input_audio_transcription.delta":
        await ws.send_json({"type": "asr_text", "text": d.get("delta", "")})

    elif t == "conversation.item.input_audio_transcription.completed":
        await ws.send_json({"type": "asr_text", "text": d.get("delta", ""), "final": True})

    elif t == "response.output_text.delta":
        await ws.send_json({"type": "chat_text", "content": d.get("delta", "")})

    elif t == "response.output_audio.delta":
        b64 = d.get("delta", "")
        if b64:
            await ws.send_bytes(base64.b64decode(b64))

    elif t == "response.done":
        await ws.send_json({"type": "chat_ended"})

    elif t == "error":
        logger.error("火山错误: %s", json.dumps(d, ensure_ascii=False)[:500])
        await ws.send_json({"type": "error", "message": str(d.get("message") or d)})


# 静态文件挂载放最后，避免覆盖 /ws 路由
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


if __name__ == "__main__":
    import uvicorn
    logger.info("M1 后端启动: http://localhost:%d (WS: /ws)", PORT)
    if not API_KEY:
        logger.warning("[!] 未配置 VOLCENGINE_API_KEY，请在 server/.env 填写后重启")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
