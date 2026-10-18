import asyncio
import json
import unittest
from unittest.mock import patch
import httpx
import llm


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_story_instruction_reaches_stream_request_without_changing_normal_chat(self):
        captured = []
        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"小兔子来了。"}}]}\n\ndata: [DONE]\n\n')
        factory = httpx.AsyncClient
        with patch.object(llm, 'LLM_API_KEY', 'test'), patch.object(llm.httpx, 'AsyncClient', side_effect=lambda **kw: factory(transport=httpx.MockTransport(handler), **kw)):
            [text async for text in llm.chat_stream('去海底', [], '', instruction='每轮只讲一段互动故事。')]
            [text async for text in llm.chat_stream('你好')]
        self.assertIn('每轮只讲一段互动故事。', captured[0]['messages'][0]['content'])
        self.assertNotIn('每轮只讲一段互动故事。', captured[1]['messages'][0]['content'])

    async def test_reads_incremental_content_and_closes_transport(self):
        self.assertTrue(hasattr(llm, 'chat_stream'), 'LLM incremental streaming API is missing')
        closed = asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b': heartbeat\n\ndata: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
                payload = json.dumps({'choices':[{'delta':{'content':'你好。'}}]},ensure_ascii=False).encode()
                yield b'data: ' + payload[:12]
                yield payload[12:] + b'\n\ndata: [DONE]\n\n'
            async def aclose(self):
                closed.set()
        def handler(request):
            self.assertTrue(json.loads(request.content)['stream'])
            return httpx.Response(200, stream=Body())
        factory = httpx.AsyncClient
        with patch.object(llm, 'LLM_API_KEY', 'test'), patch.object(llm.httpx, 'AsyncClient', side_effect=lambda **kw: factory(transport=httpx.MockTransport(handler),**kw)):
            self.assertEqual([s async for s in llm.chat_stream('你好')], ['你好。'])
        self.assertTrue(closed.is_set())

    async def test_http_failure_is_not_silently_treated_as_empty_success(self):
        self.assertTrue(hasattr(llm, 'chat_stream'), 'LLM incremental streaming API is missing')
        factory = httpx.AsyncClient
        with patch.object(llm, 'LLM_API_KEY', 'test'), patch.object(llm.httpx, 'AsyncClient', side_effect=lambda **kw: factory(transport=httpx.MockTransport(lambda req: httpx.Response(401)),**kw)):
            with self.assertRaises(httpx.HTTPStatusError):
                [s async for s in llm.chat_stream('你好')]


if __name__ == '__main__':
    unittest.main()
