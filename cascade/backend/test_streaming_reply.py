import asyncio
import importlib
import importlib.util
import unittest


class ReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('reply'), 'Streaming reply module is missing')
        self.module = importlib.import_module('reply')

    def test_sentence_buffer_keeps_split_punctuation_and_final_tail(self):
        buffer = self.module.SentenceBuffer()
        self.assertEqual(buffer.feed('你好'), [])
        self.assertEqual(buffer.feed('呀。接下来'), ['你好呀。'])
        self.assertEqual(buffer.feed('说什么？最后'), ['接下来说什么？'])
        self.assertEqual(buffer.finish(), ['最后'])

    def test_unpunctuated_text_is_bounded_without_losing_characters(self):
        buffer = self.module.SentenceBuffer(max_chars=20)
        segments = buffer.feed('a' * 55) + buffer.finish()
        self.assertEqual(''.join(segments), 'a' * 55)
        self.assertTrue(all(len(s) <= 20 for s in segments))

    def test_trailing_quote_is_not_synthesized_as_a_separate_empty_sentence(self):
        buffer = self.module.SentenceBuffer()
        self.assertEqual(buffer.feed('“你好。'), ['“你好。'])
        self.assertEqual(buffer.feed('”'), [])
        self.assertEqual(buffer.finish(), [])

    async def test_audio_starts_before_llm_finishes_and_ack_requires_audio_end(self):
        events = []
        allow_finish = asyncio.Event()
        first_audio = asyncio.Event()

        async def send(event):
            events.append(event)
            if event['type'] == 'ai_audio':
                first_audio.set()

        async def text():
            yield '第一句。'
            await allow_finish.wait()
            yield '第二句。'

        async def tts(sentence):
            yield b'\x01\x00' * 20

        output = self.module.Reply(7, send, self.module.TurnTiming(), lambda: True)
        task = asyncio.create_task(output.generate(text(), tts))
        try:
            await asyncio.wait_for(first_audio.wait(), 1)
            self.assertFalse(task.done(), 'LLM must still be streaming')
            self.assertFalse(output.acknowledge(7), 'Early playback acknowledgement must be rejected')
            allow_finish.set()
            self.assertEqual(await task, '第一句。第二句。')
            self.assertEqual(events[-1]['type'], 'audio_end')
            self.assertFalse(output.acknowledge(6), 'Old turn must not finish this reply')
            self.assertFalse(output.acknowledge(None))
            self.assertTrue(output.acknowledge(7))
            await asyncio.wait_for(output.wait_played(), 1)
            self.assertTrue(all(e['turn_id'] == 7 for e in events))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_cancellation_closes_llm_and_tts_generators(self):
        entered = asyncio.Event()
        llm_closed = asyncio.Event()
        tts_closed = asyncio.Event()

        async def text():
            try:
                yield '第一句。'
                await asyncio.Event().wait()
            finally:
                llm_closed.set()

        async def tts(sentence):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield b'\0\0'
            finally:
                tts_closed.set()

        async def send(event):
            pass

        output = self.module.Reply(1, send, self.module.TurnTiming(), lambda: True)
        task = asyncio.create_task(output.generate(text(), tts))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(llm_closed.is_set())
        self.assertTrue(tts_closed.is_set())

    async def test_stale_output_never_sends_events(self):
        events = []
        async def send(event):
            events.append(event)
        async def text():
            yield '旧回复。'
        async def tts(sentence):
            yield b'\0\0'
        output = self.module.Reply(1, send, self.module.TurnTiming(), lambda: False)
        with self.assertRaises(asyncio.CancelledError):
            await output.generate(text(), tts)
        self.assertEqual(events, [])


if __name__ == '__main__':
    unittest.main()
