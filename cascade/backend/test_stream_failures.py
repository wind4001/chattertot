import asyncio
import base64
import importlib
import unittest


class StreamFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_tts_failure_cancels_the_still_running_llm(self):
        from reply import Reply, ReplyError, TurnTiming
        closed = asyncio.Event()
        async def text():
            try:
                yield '第一句。'
                await asyncio.Event().wait()
            finally:
                closed.set()
        async def tts(sentence):
            raise RuntimeError('tts unavailable')
            yield b''
        async def send(event):
            pass
        output = Reply(1, send, TurnTiming(), lambda: True)
        with self.assertRaises(ReplyError) as failure:
            await output.generate(text(), tts)
        self.assertEqual(failure.exception.stage, 'tts')
        self.assertTrue(closed.is_set())

    async def test_odd_tts_chunks_are_joined_without_losing_pcm_samples(self):
        from reply import Reply, TurnTiming
        events = []
        async def send(event):
            events.append(event)
        async def text():
            yield '你好。'
        async def tts(sentence):
            yield b'\x01'
            yield b'\x00\x02'
            yield b'\x00'
        output = Reply(1, send, TurnTiming(), lambda: True)
        await output.generate(text(), tts)
        audio = b''.join(base64.b64decode(e['audio']) for e in events if e['type'] == 'ai_audio')
        self.assertEqual(audio, b'\x01\x00\x02\x00')
        self.assertTrue(all(len(base64.b64decode(e['audio'])) % 2 == 0 for e in events if e['type'] == 'ai_audio'))

    async def test_empty_audio_is_a_visible_failure_not_success(self):
        from reply import Reply, ReplyError, TurnTiming
        async def send(event):
            pass
        async def text():
            yield '你好。'
        async def tts(sentence):
            if False:
                yield b''
        output = Reply(1, send, TurnTiming(), lambda: True)
        with self.assertRaises(ReplyError) as failure:
            await output.generate(text(), tts)
        self.assertEqual(failure.exception.stage, 'tts')


if __name__ == '__main__':
    unittest.main()
