"""按句合成、轮次确认与阶段耗时；不依赖具体 LLM/TTS 供应商。"""
import asyncio
import base64
from contextlib import aclosing
import json
import re
import time
import uuid


class SentenceBuffer:
    def __init__(self, max_chars=100):
        self.text = ""
        self.max_chars = max_chars

    def feed(self, delta):
        self.text += delta
        sentences = []
        while self.text:
            match = re.search(r"[。！？!?；;\n]", self.text)
            end = match.end() if match else len(self.text) + 1
            if end > self.max_chars and len(self.text) >= self.max_chars:
                prefix = self.text[:self.max_chars]
                comma = max(prefix.rfind("，"), prefix.rfind(","), prefix.rfind(" "))
                end = comma + 1 if comma >= self.max_chars // 2 else self.max_chars
            elif end > len(self.text):
                break
            sentence, self.text = self.text[:end], self.text[end:]
            if any(character.isalnum() for character in sentence):
                sentences.append(sentence)
        return sentences

    def finish(self):
        tail, self.text = self.text, ""
        return [tail] if any(character.isalnum() for character in tail) else []


class TurnTiming:
    def __init__(self, start=None):
        self.start = time.monotonic() if start is None else start
        self.trace_id = uuid.uuid4().hex[:12]
        self.turn_id = None
        self.seen = set()

    def mark(self, stage, **fields):
        if stage in self.seen:
            return
        self.seen.add(stage)
        print("[TIMING] " + json.dumps({
            "trace_id": self.trace_id, "turn_id": self.turn_id,
            "stage": stage, "elapsed_ms": round((time.monotonic() - self.start) * 1000),
            **fields,
        }, ensure_ascii=False), flush=True)


class ReplyError(Exception):
    def __init__(self, stage):
        self.stage = stage
        super().__init__(stage)


class Reply:
    def __init__(self, turn_id, send, timing, is_current):
        self.turn_id = turn_id
        self.send_event = send
        self.timing = timing
        self.timing.turn_id = turn_id
        self.is_current = is_current
        self.finished = False
        self.played = asyncio.Event()
        self.pcm_bytes = 0
        self.first_audio_at = None
        self.audio_deadline = time.monotonic()
        self.text = ""

    async def send(self, kind, **fields):
        if not self.is_current():
            raise asyncio.CancelledError
        await self.send_event({"type": kind, "turn_id": self.turn_id, **fields})

    def acknowledge(self, turn_id):
        if type(turn_id) is not int or turn_id != self.turn_id or not self.finished:
            return False
        if not self.is_current() or self.played.is_set():
            return False
        self.played.set()
        self.timing.mark("play_end")
        return True

    async def generate(self, text_stream, synthesize, source="llm"):
        await self.send("turn_start")
        queue = asyncio.Queue(maxsize=2)

        async def produce():
            buffer = SentenceBuffer()
            try:
                async with aclosing(text_stream):
                    async for delta in text_stream:
                        self.timing.mark(f"{source}_first_text")
                        self.text += delta
                        await self.send("ai_text_delta", text=delta)
                        for sentence in buffer.feed(delta):
                            await queue.put(sentence)
                if not self.text.strip():
                    raise RuntimeError("Empty reply")
                self.timing.mark(f"{source}_done")
                for sentence in buffer.finish():
                    await queue.put(sentence)
                await queue.put(None)
            except Exception as error:
                await queue.put(ReplyError("llm"))
                self.timing.mark("llm_error", error_type=type(error).__name__)

        producer = asyncio.create_task(produce())
        try:
            while True:
                sentence = await queue.get()
                if sentence is None:
                    break
                if isinstance(sentence, ReplyError):
                    raise sentence
                self.timing.mark("tts_start")
                sentence_bytes = 0
                carry = b""
                try:
                    async with aclosing(synthesize(sentence)) as stream, asyncio.timeout(30):
                        async for chunk in stream:
                            carry += chunk
                            count = len(carry) - len(carry) % 2
                            if not count:
                                continue
                            pcm, carry = carry[:count], carry[count:]
                            self.timing.mark("first_audio")
                            now = time.monotonic()
                            if self.first_audio_at is None:
                                self.first_audio_at = now
                            self.audio_deadline = max(self.audio_deadline, now) + len(pcm) / 48000
                            self.pcm_bytes += len(pcm)
                            sentence_bytes += len(pcm)
                            await self.send("ai_audio", audio=base64.b64encode(pcm).decode("ascii"), sample_rate=24000)
                    if carry or not sentence_bytes:
                        raise RuntimeError("Invalid or empty TTS audio")
                except Exception as error:
                    self.timing.mark("tts_error", error_type=type(error).__name__)
                    raise ReplyError("tts") from error
            if not self.pcm_bytes:
                raise ReplyError("llm")
            await self.send("ai_text", text=self.text)
            await self.finish()
            return self.text
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def finish(self):
        if self.finished:
            return
        await self.send("audio_end")
        self.finished = True
        self.timing.mark("audio_end", audio_ms=round(self.pcm_bytes / 48))

    async def wait_played(self):
        remaining = max(0, self.audio_deadline - time.monotonic()) + 2.0
        try:
            await asyncio.wait_for(self.played.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            self.timing.mark("playback_timeout")
