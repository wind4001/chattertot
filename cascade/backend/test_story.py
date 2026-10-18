import unittest
import asyncio
from unittest.mock import AsyncMock, patch

from story import StorySession


class StoryTests(unittest.TestCase):
    def test_one_choice_at_a_time_then_child_drives_plot(self):
        story = StorySession()
        role = story.begin('给我讲个故事吧')
        self.assertEqual(story.phase, 'role')
        self.assertEqual(role.reply.count('？'), 1)
        scene = story.begin('我想当小恐龙')
        self.assertEqual(story.phase, 'scene')
        self.assertIn('哪里', scene.reply)
        opening = story.begin('去海底')
        self.assertEqual(story.phase, 'playing')
        self.assertIn('小恐龙', opening.instruction)
        self.assertIn('海底', opening.instruction)
        story.finish('小恐龙发现一扇贝壳门。你想敲门还是找钥匙？')
        change = story.begin('我不想敲门，我要变成鲸鱼游进去')
        self.assertIsNone(change.reply)
        self.assertTrue(any('贝壳门' in m['content'] for m in change.history))
        self.assertEqual(story.messages[-1]['content'], '我不想敲门，我要变成鲸鱼游进去')

    def test_explicit_details_skip_repeated_questions(self):
        story = StorySession()
        plan = story.begin('讲一个小兔子在森林探险的故事')
        self.assertEqual(story.phase, 'playing')
        self.assertIsNone(plan.reply)

    def test_exit_and_restart_are_local_and_clear_old_story(self):
        first, second = StorySession(), StorySession()
        self.assertIsNotNone(first.begin('一起编故事'))
        self.assertIsNone(second.begin('你好'))
        first.begin('小兔子')
        first.begin('森林')
        first.finish('找到了神秘钥匙。')
        first.begin('换个故事')
        self.assertEqual(first.phase, 'role')
        self.assertFalse(any('神秘钥匙' in m['content'] for m in first.messages))
        exit_plan = first.begin('不玩故事了')
        self.assertIn('聊天', exit_plan.reply)
        self.assertEqual(first.phase, 'off')
        self.assertIsNone(first.begin('今天下雨了吗'))

    def test_negative_story_request_does_not_enter_story(self):
        for text in ['不要讲故事', '我不想听故事', '故事是什么意思', '你好']:
            story = StorySession()
            self.assertIsNone(story.begin(text), text)
            self.assertEqual(story.phase, 'off')

    def test_child_can_delegate_choices_and_finish(self):
        story = StorySession()
        story.begin('讲故事')
        story.begin('你帮我选吧')
        plan = story.begin('都可以')
        self.assertIn('小兔子', plan.instruction)
        self.assertIn('森林', plan.instruction)
        ending = story.begin('给它一个结局吧')
        self.assertIn('结局', ending.instruction)
        story.finish('小兔子回家了。', ending=True)
        self.assertEqual(story.phase, 'off')

    def test_short_choices_repeat_and_natural_exit(self):
        story = StorySession()
        story.begin('一起编故事')
        self.assertIn('小兔子', story.begin('没听清，再说一遍').reply)
        self.assertEqual(story.phase, 'role')
        story.begin('第一个')
        plan = story.begin('第二个')
        self.assertIn('小兔子', plan.instruction)
        self.assertIn('海底', plan.instruction)
        self.assertIsNotNone(story.begin('不玩了'))
        self.assertEqual(story.phase, 'off')

    def test_explicit_story_request_can_answer_role_question(self):
        story = StorySession()
        story.begin('一起编故事')
        plan = story.begin('讲个小恐龙在海底的故事')
        self.assertEqual(story.phase, 'playing')
        self.assertIn('海底', plan.instruction)

    def test_negative_plot_change_is_not_a_request_to_exit(self):
        story = StorySession()
        story.begin('讲个小兔子在森林的故事')
        plan = story.begin('我不想让故事里的小兔子受伤')
        self.assertEqual(story.phase, 'playing')
        self.assertIsNone(plan.reply)

    def test_interrupted_segment_remains_available_as_unconfirmed_context(self):
        story = StorySession()
        story.begin('讲个小兔子在海底的故事')
        story.interrupt('小兔子发现了一扇贝壳门。')
        plan = story.begin('先不要开那扇门')
        self.assertIn('贝壳门', str(plan.history))
        self.assertIn('被打断', str(plan.history))

    def test_only_bounded_local_history_is_sent(self):
        story = StorySession()
        story.begin('小兔子在森林的故事，给我讲一个故事')
        for _ in range(40):
            story.begin('继续')
            story.finish('小兔子往前走。')
        self.assertLessEqual(len(story.messages), 40)


class StorySocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_kws_interruption_preserves_partial_story_for_next_turn(self):
        import app
        from test_task_cleanup import Socket
        socket = Socket()
        histories = []
        async def stream(text, history=None, **kwargs):
            histories.append(history)
            yield '小兔子找到了一扇贝壳门。'
            if len(histories) == 1:
                await asyncio.Event().wait()
        async def tts(text):
            yield b'\0\0' * 800
        with (
            patch.object(app, 'asr_text', AsyncMock(side_effect=['小云小云，讲个小兔子在海底的故事', '小云小云，先不要开那扇门'])),
            patch.object(app, 'kws_detect', AsyncMock(return_value={'detected': True})),
            patch.object(app.llm, 'chat_stream', stream),
            patch.object(app.tts, 'synthesize_stream', tts),
            patch.object(app.db, 'add_message', AsyncMock()) as save,
            patch.object(app, 'summarize_session', AsyncMock()),
        ):
            task = asyncio.create_task(app.ws_endpoint(socket))
            try:
                for count in (1, 2):
                    await socket.incoming.put({'type': 'websocket.receive', 'bytes': b'\xff\x7f' * 1600 + b'\0\0' * 24000})
                    async with asyncio.timeout(1):
                        while sum(e['type'] == 'ai_audio' for e in socket.events) < count:
                            await asyncio.sleep(0.001)
                self.assertIn('贝壳门', str(histories[1]))
                self.assertIn('被打断', str(histories[1]))
                self.assertTrue(any(e['type'] == 'user_speaking' for e in socket.events))
                save.assert_not_awaited()
            finally:
                await socket.incoming.put({'type': 'websocket.disconnect'})
                await asyncio.wait_for(task, 1)

    async def test_story_uses_local_context_and_never_saves_fiction_as_real_memory(self):
        import app
        from test_task_cleanup import Socket
        socket = Socket()
        calls = []
        async def stream(text, history=None, facts='', **kwargs):
            calls.append((text, history, facts, kwargs))
            yield '小兔子发现一扇贝壳门。你想敲门还是找钥匙？'
        async def tts(text):
            yield b'\0\0' * 800
        texts = ['小云小云，一起编故事', '小兔子', '海底', '我想变成鲸鱼游进去', '小云小云，换个故事', '小云小云，不玩了', '你好']
        get_history = AsyncMock(return_value=[{'role': 'user', 'content': '真实聊天记录'}])
        save = AsyncMock()
        with (
            patch.object(app, 'asr_text', AsyncMock(side_effect=texts)),
            patch.object(app, 'kws_detect', AsyncMock(return_value={'detected': True})),
            patch.object(app, 'extract_embedding', AsyncMock(return_value=[1, 0])),
            patch.object(app.llm, 'chat_stream', stream),
            patch.object(app.tts, 'synthesize_stream', tts),
            patch.object(app.db, 'get_recent_messages', get_history),
            patch.object(app.db, 'get_profile', AsyncMock(return_value={'facts': '真实档案'})),
            patch.object(app.db, 'add_message', save),
            patch.object(app, 'summarize_session', AsyncMock()),
        ):
            task = asyncio.create_task(app.ws_endpoint(socket))
            try:
                for count, _ in enumerate(texts, 1):
                    await socket.incoming.put({'type': 'websocket.receive', 'bytes': b'\xff\x7f' * 1600 + b'\0\0' * 24000})
                    async with asyncio.timeout(1):
                        while sum(e['type'] == 'audio_end' for e in socket.events) < count:
                            await asyncio.sleep(0.001)
                    end = [e for e in socket.events if e['type'] == 'audio_end'][-1]
                    await socket.incoming.put({'type': 'websocket.receive', 'text': __import__('json').dumps({'type': 'play_end', 'turn_id': end['turn_id']})})
                    await asyncio.sleep(0.01)
                    if count < len(texts):
                        save.assert_not_awaited()
                        get_history.assert_not_awaited()
                self.assertEqual(get_history.await_count, 1)
                self.assertEqual(save.await_count, 2)
                self.assertEqual(len(calls), 3)
                self.assertEqual(calls[0][2], '')
                self.assertNotIn('真实聊天记录', str(calls[0][1]))
                self.assertIn('贝壳门', str(calls[1][1]))
                self.assertIn('instruction', calls[1][3])
                self.assertEqual(calls[2][2], '真实档案')
            finally:
                await socket.incoming.put({'type': 'websocket.disconnect'})
                await asyncio.wait_for(task, 1)
