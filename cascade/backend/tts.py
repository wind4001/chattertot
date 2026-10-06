"""TTS 客户端：豆包语音合成 2.0（seed-tts-2.0），文本 -> mp3 音频。"""
import base64
import json
import os
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

TTS_API_KEY = os.getenv("TTS_API_KEY", "")
TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "zh_female_vv_uranus_bigtts")


async def synthesize(text: str) -> bytes:
    """文本 -> mp3 音频字节（整段，用于测试接口）。"""
    if not TTS_API_KEY:
        return b""
    headers = {
        "X-Api-Key": TTS_API_KEY,
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    body = {
        "user": {"uid": "test_user"},
        "req_params": {
            "text": text,
            "speaker": TTS_SPEAKER,
            "model": "seed-tts-2.0-standard",
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
                "speech_rate": 0,
                "loudness_rate": 0,
            },
        },
    }
    audio = bytearray()
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        async with client.stream("POST", TTS_URL, headers=headers, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    d = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if d.get("code") in (0, 20000000):
                    b64 = d.get("data", "")
                    if b64:
                        audio += base64.b64decode(b64)
    return bytes(audio)


async def synthesize_stream(text: str, sample_rate: int = 24000):
    """整段文本 -> 逐块 yield PCM 字节（16bit，流式，首包 <300ms）。"""
    if not TTS_API_KEY:
        return
    headers = {
        "X-Api-Key": TTS_API_KEY,
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    body = {
        "user": {"uid": "test_user"},
        "req_params": {
            "text": text,
            "speaker": TTS_SPEAKER,
            "model": "seed-tts-2.0-standard",
            "audio_params": {
                "format": "pcm",
                "sample_rate": sample_rate,
            },
        },
    }
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        async with client.stream("POST", TTS_URL, headers=headers, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    d = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if d.get("code") in (0, 20000000) and d.get("data"):
                    yield base64.b64decode(d["data"])
