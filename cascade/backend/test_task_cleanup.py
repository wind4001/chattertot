import asyncio
import unittest
from unittest.mock import patch

import app


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.events = []

    async def accept(self):
        pass

    async def send_json(self, event):
        self.events.append(event)

    async def receive(self):
        return await self.incoming.get()


class TaskCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_cancels_pending_wake_detection(self):
        socket = Socket()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def detect(_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def summarize():
            pass

        with patch.object(app, 'kws_detect', detect), patch.object(app, 'summarize_session', summarize):
            endpoint = asyncio.create_task(app.ws_endpoint(socket))
            await socket.incoming.put({'type': 'websocket.receive', 'bytes': b'\xff\x7f' * 1600})
            await socket.incoming.put({'type': 'websocket.receive', 'bytes': b'\0\0' * 24000})
            await asyncio.wait_for(started.wait(), 1)
            await socket.incoming.put({'type': 'websocket.disconnect'})
            await asyncio.wait_for(endpoint, 1)
            self.assertTrue(cancelled.is_set(), 'Disconnected socket left its model task running')


if __name__ == '__main__':
    unittest.main()
