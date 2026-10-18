import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch
import app
from test_task_cleanup import Socket


class PlaybackProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_detector_ownership_is_held_until_old_audio_stream_closes(self):
        socket = Socket()
        closing = asyncio.Event()
        release = asyncio.Event()
        calls = 0
        async def tts(text):
            nonlocal calls
            calls += 1
            number = calls
            try:
                yield b'\0\0' * 800
                await asyncio.Event().wait()
            finally:
                if number == 1:
                    closing.set()
                    await release.wait()
        async def chat(*args):
            yield '一个故事。'
        async def speech():
            await socket.incoming.put({'type':'websocket.receive', 'bytes':b'\xff\x7f' * 1600})
            await socket.incoming.put({'type':'websocket.receive', 'bytes':b'\0\0' * 24000})
        kws = AsyncMock(return_value={'detected':True})
        with (
            patch.object(app, 'kws_detect', kws),
            patch.object(app, 'asr_text', AsyncMock(return_value='小云小云，解释彩虹')),
            patch.object(app.tts, 'synthesize_stream', tts),
            patch.object(app.llm, 'chat_stream', chat),
            patch.object(app, 'summarize_session', AsyncMock()),
            patch.object(app.db, 'get_recent_messages', AsyncMock(return_value=[])),
            patch.object(app.db, 'get_profile', AsyncMock(return_value={'facts':''})),
        ):
            endpoint = asyncio.create_task(app.ws_endpoint(socket))
            try:
                await speech()
                async with asyncio.timeout(1):
                    while not any(e['type']=='ai_audio' for e in socket.events):
                        await asyncio.sleep(0.001)
                await speech()
                await asyncio.wait_for(closing.wait(),1)
                await speech()
                await asyncio.sleep(0.02)
                self.assertEqual(kws.await_count, 2, 'A second detector took ownership during cancellation')
            finally:
                release.set()
                await socket.incoming.put({'type':'websocket.disconnect'})
                await asyncio.wait_for(endpoint,1)

    async def test_replacement_reply_can_be_interrupted_again(self):
        socket = Socket()
        async def tts(text):
            yield b'\0\0' * 800
            await asyncio.Event().wait()
        async def chat(*args):
            yield '一个故事。'
            await asyncio.Event().wait()
        async def speech():
            await socket.incoming.put({'type':'websocket.receive', 'bytes':b'\xff\x7f' * 1600})
            await socket.incoming.put({'type':'websocket.receive', 'bytes':b'\0\0' * 24000})
        async def wait_for_audio(count):
            async with asyncio.timeout(1):
                while sum(e['type']=='ai_audio' for e in socket.events) < count:
                    await asyncio.sleep(0.001)
        with (
            patch.object(app, 'kws_detect', AsyncMock(return_value={'detected':True})),
            patch.object(app, 'asr_text', AsyncMock(return_value='小云小云，解释彩虹')),
            patch.object(app.tts, 'synthesize_stream', tts),
            patch.object(app.llm, 'chat_stream', chat),
            patch.object(app, 'summarize_session', AsyncMock()),
            patch.object(app.db, 'get_recent_messages', AsyncMock(return_value=[])),
            patch.object(app.db, 'get_profile', AsyncMock(return_value={'facts':''})),
        ):
            endpoint = asyncio.create_task(app.ws_endpoint(socket))
            try:
                await speech()
                await wait_for_audio(1)
                await speech()
                await wait_for_audio(2)
                await speech()
                try:
                    await wait_for_audio(3)
                except TimeoutError:
                    self.fail('Second successful interruption was suppressed')
                starts = [e['turn_id'] for e in socket.events if e['type']=='turn_start']
                self.assertEqual(len(starts), 3)
                self.assertEqual(starts, sorted(set(starts)))
            finally:
                await socket.incoming.put({'type':'websocket.disconnect'})
                await asyncio.wait_for(endpoint,1)

    async def test_old_play_end_does_not_release_current_reply(self):
        socket = Socket()
        async def tts(text):
            yield b'\0\0' * 800
        async def chat(*args):
            yield '你好。'
        asr = AsyncMock(side_effect=['小云小云', '你好'])
        kws = AsyncMock(side_effect=[{'detected':True}, {'detected':False}, {'detected':False}])
        async def wait_for(predicate):
            async with asyncio.timeout(1):
                while not predicate():
                    await asyncio.sleep(0.001)
        async def speech():
            await socket.incoming.put({'type':'websocket.receive', 'bytes':b'\xff\x7f' * 1600})
            await socket.incoming.put({'type':'websocket.receive', 'bytes':b'\0\0' * 24000})
        async def acknowledge(turn_id):
            await socket.incoming.put({'type':'websocket.receive','text':json.dumps({'type':'play_end','turn_id':turn_id})})
        with (
            patch.object(app, 'kws_detect', kws),
            patch.object(app, 'asr_text', asr),
            patch.object(app.tts, 'synthesize_stream', tts),
            patch.object(app.llm, 'chat_stream', chat),
            patch.object(app, 'summarize_session', AsyncMock()),
            patch.object(app.db, 'get_recent_messages', AsyncMock(return_value=[])),
            patch.object(app.db, 'get_profile', AsyncMock(return_value={'facts':''})),
            patch.object(app.db, 'add_message', AsyncMock()),
        ):
            endpoint = asyncio.create_task(app.ws_endpoint(socket))
            try:
                await speech()
                await wait_for(lambda:any(e['type']=='audio_end' for e in socket.events))
                first = next(e['turn_id'] for e in socket.events if e['type']=='turn_start')
                await acknowledge(first-1)
                await speech()
                await wait_for(lambda:kws.await_count==2)
                self.assertEqual(asr.await_count, 1, 'Old acknowledgement released a busy reply')
                await acknowledge(first)
                await asyncio.sleep(0.01)
                await speech()
                await wait_for(lambda:sum(e['type']=='audio_end' for e in socket.events)==2)
                self.assertEqual(asr.await_count, 2)
                await acknowledge(first)
                await speech()
                await wait_for(lambda:kws.await_count==3)
                self.assertEqual(asr.await_count, 2, 'Old turn finished a newer reply')
            finally:
                await socket.incoming.put({'type':'websocket.disconnect'})
                await asyncio.wait_for(endpoint,1)


if __name__ == '__main__':
    unittest.main()
