import array
import asyncio
import random
import unittest
from unittest.mock import AsyncMock, patch

from endpointing import EndpointDetector


def pcm(amplitude, milliseconds):
    # Alternating samples have zero DC, unlike a constant int16 test buffer.
    return array.array('h', [amplitude, -amplitude] * (8 * milliseconds)).tobytes()


class EndpointTests(unittest.TestCase):
    def test_child_pause_stays_in_one_turn(self):
        detector = EndpointDetector()
        events = detector.feed(pcm(1200, 400) + pcm(0, 1000) + pcm(1100, 400))
        self.assertEqual([e.kind for e in events], ['start'])
        events = detector.feed(pcm(0, 1400))
        self.assertEqual([e.kind for e in events], ['end'])
        self.assertIn(pcm(0, 1000), events[0].pcm)

    def test_steady_background_does_not_extend_endlessly(self):
        detector = EndpointDetector()
        self.assertEqual(detector.feed(pcm(220, 2000)), [])
        detector.feed(pcm(1200, 400))
        events = detector.feed(pcm(350, 1600))
        self.assertEqual([e.kind for e in events], ['end'])

    def test_broadband_background_with_clicks_ends_without_extra_turns(self):
        rng = random.Random(23)
        def noise(milliseconds):
            return array.array('h', [round(rng.gauss(0, 220))
                                    for _ in range(milliseconds * 16)]).tobytes()
        detector = EndpointDetector()
        self.assertEqual(detector.feed(noise(2000)), [])
        events = detector.feed(pcm(1200, 400) + noise(800) + pcm(3000, 20) + noise(800))
        self.assertEqual([e.kind for e in events], ['start', 'end'])
        self.assertEqual(detector.feed(noise(2000)), [])

    def test_short_loud_clicks_do_not_start_or_reset_a_turn(self):
        detector = EndpointDetector()
        self.assertEqual(detector.feed(pcm(2000, 20) + pcm(0, 400)), [])
        detector.feed(pcm(1200, 400))
        events = detector.feed(pcm(0, 800) + pcm(2000, 20) + pcm(0, 600))
        self.assertEqual([e.kind for e in events], ['end'])

    def test_preroll_preserves_quiet_onset(self):
        detector = EndpointDetector()
        onset = pcm(100, 100)
        detector.feed(onset + pcm(1200, 400))
        events = detector.feed(pcm(0, 1400))
        self.assertTrue(events[0].pcm.startswith(onset))

    def test_resuming_at_pause_boundary_is_not_cut_during_attack_confirmation(self):
        detector = EndpointDetector()
        detector.feed(pcm(1200, 400) + pcm(0, 1380))
        self.assertEqual(detector.feed(pcm(1200, 400)), [])
        self.assertEqual([e.kind for e in detector.feed(pcm(0, 1400))], ['end'])

    def test_long_endpoint_wait_is_not_counted_as_speaker_audio(self):
        detector = EndpointDetector()
        events = detector.feed(pcm(1200, 100) + pcm(0, 1500))
        ended = [e for e in events if e.kind == 'end'][0]
        self.assertLessEqual(len(ended.pcm), 32000 // 2)

    def test_fragmented_network_packets_do_not_change_results(self):
        stream = pcm(1200, 400) + pcm(0, 1500)
        expected = EndpointDetector().feed(stream)
        detector = EndpointDetector()
        actual = []
        for position in range(0, len(stream), 777):
            actual.extend(detector.feed(stream[position:position+777]))
        self.assertEqual(actual, expected)

    def test_long_audio_is_bounded_and_reset_drops_previous_candidates(self):
        detector = EndpointDetector()
        events = detector.feed(pcm(1200, 22000))
        ended = [e for e in events if e.kind == 'end']
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0].reason, 'max_duration')
        self.assertLessEqual(len(ended[0].pcm), 32000 * 20)
        detector.reset()
        self.assertEqual(detector.feed(pcm(0, 1400)), [])


class WebSocketEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_pause_does_not_submit_a_partial_utterance(self):
        import app
        from test_task_cleanup import Socket
        socket = Socket()
        kws = AsyncMock(return_value={'detected': False})
        with patch.object(app, 'kws_detect', kws), patch.object(app, 'summarize_session', AsyncMock()):
            task = asyncio.create_task(app.ws_endpoint(socket))
            try:
                await socket.incoming.put({'type': 'websocket.receive', 'bytes': pcm(1200, 400) + pcm(0, 1000)})
                await asyncio.sleep(0.02)
                kws.assert_not_awaited()
                await socket.incoming.put({'type': 'websocket.receive', 'bytes': pcm(1100, 400) + pcm(0, 1500)})
                async with asyncio.timeout(1):
                    while kws.await_count == 0:
                        await asyncio.sleep(0.001)
                kws.assert_awaited_once()
            finally:
                await socket.incoming.put({'type': 'websocket.disconnect'})
                await asyncio.wait_for(task, 1)
