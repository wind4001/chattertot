import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import app
from test_task_cleanup import Socket


class DialogueDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_cancels_active_reply(self):
        socket = Socket()
        llm_started = asyncio.Event()
        llm_cancelled = asyncio.Event()

        async def kws(_):
            return {'detected': True}

        async def asr(_):
            return '小云小云，你好'

        async def chat(*args):
            llm_started.set()
            try:
                await asyncio.Event().wait()
                yield "你好。"
            finally:
                llm_cancelled.set()

        async def summarize():
            pass

        with (
            patch.object(app, 'kws_detect', kws),
            patch.object(app, 'asr_text', asr),
            patch.object(app.llm, 'chat_stream', chat),
            patch.object(app, 'summarize_session', summarize),
            patch.object(app.db, 'get_recent_messages', AsyncMock(return_value=[])),
            patch.object(app.db, 'get_profile', AsyncMock(return_value={'facts': ''})),
        ):
            endpoint = asyncio.create_task(app.ws_endpoint(socket))
            await socket.incoming.put({'type': 'websocket.receive', 'bytes': b'\xff\x7f' * 1600})
            await socket.incoming.put({'type': 'websocket.receive', 'bytes': b'\0\0' * 24000})
            await asyncio.wait_for(llm_started.wait(), 5)
            await socket.incoming.put({'type': 'websocket.disconnect'})
            await asyncio.wait_for(endpoint, 1)
            self.assertTrue(llm_cancelled.is_set())


if __name__ == '__main__':
    unittest.main()
