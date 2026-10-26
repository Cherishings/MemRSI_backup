"""Integration contracts, not evidence that the research hypothesis is true.

Run with a pristine PAOS package on PYTHONPATH. No model/network request occurs.
"""
import asyncio
import copy
import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PhyAgentOS.providers.base import LLMResponse, ToolCallRequest
from PhyAgentOS.providers.custom_provider import CustomProvider

from agent_adapter import Agent
from model_provider import Provider


POLICY = {'schema': 1, 'guidance': 'TEST_GUIDANCE_PROCEDURE', 'update': 'TEST_UPDATE_PROCEDURE'}


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def make(self, root, arm):
        output = root / 'cases' / arm
        policy = root / 'policy.json'
        policy.write_text(json.dumps(POLICY))
        with patch('model_provider.read_api_key', return_value='LOCAL_TEST_KEY'):
            return Agent(arm, output, policy if arm == 'memrsi' else None)

    async def test_baseline_has_no_added_policy_and_both_interfaces_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = [self.make(root, arm) for arm in ('native', 'memrsi')]
            try:
                self.assertEqual(agents[0].loop.max_iterations, 40)
                self.assertEqual(agents[1].loop.max_iterations, 40)
                self.assertEqual(agents[0].loop.tools.get_definitions(), agents[1].loop.tools.get_definitions())
                self.assertEqual((agents[0].workspace / 'TOOLS.md').read_bytes(), (agents[1].workspace / 'TOOLS.md').read_bytes())
                self.assertIsNone(agents[0].ops)
                for agent in agents:
                    for name in ('TASK.md', 'LESSONS.md', 'LONG_MEMORY.json', 'SHORT_MEMORY.json'):
                        self.assertFalse((agent.workspace / name).exists())
                    await agent.action.execute('finish', 'The code must not veto this decision.')
                    self.assertEqual(agent.action.records[0]['skill'], 'finish')
                    self.assertNotIn('update_mission_memory', agent.loop.tools.tool_names)
                with self.assertRaisesRegex(ValueError, 'baseline_has_no_added_policy'):
                    Agent('native', root / 'invalid', root / 'policy.json')
            finally:
                for agent in agents:
                    await agent.close()

    async def test_latest_feedback_archived_before_clear_both_arms(self):
        for arm in ('native', 'memrsi'):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as directory:
                agent = self.make(Path(directory), arm)
                try:
                    memory = agent.workspace / 'memory/MEMORY.md'
                    memory.write_text('STALE_STATE: temporary order pending; main mission pending.')
                    await agent.observe_only('Main mission: serve table one after this order.', {'expected': 'PRIVATE_SENTINEL'})
                    await agent.observe_only('Latest public execution feedback: order completed. LATEST_EVENT.', {'private': 'PRIVATE_SENTINEL'})
                    if arm == 'memrsi':
                        (agent.workspace / 'TASK.md').write_text('STALE_GUIDANCE')
                    requests = []

                    async def archive(provider, **kwargs):
                        requests.append(kwargs)
                        text = json.dumps(kwargs)
                        self.assertIn('LATEST_EVENT', text)
                        self.assertNotIn('PRIVATE_SENTINEL', text)
                        self.assertNotIn('STALE_GUIDANCE', text)
                        self.assertEqual('TEST_UPDATE_PROCEDURE' in text, arm == 'memrsi')
                        self.assertGreater(len(agent.loop.sessions.get_or_create(agent.session_key).messages), 0)
                        return LLMResponse(content=None, tool_calls=[ToolCallRequest('archive', 'save_memory', {
                            'history_entry': 'The temporary order completed.',
                            'memory_update': 'FRESH_STATE: temporary order done; table one pending.',
                        })])

                    with patch.object(Provider, '_chat_attempts', archive):
                        await agent.rollover()
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(agent.loop.sessions.get_or_create(agent.session_key).messages, [])
                    self.assertIn('FRESH_STATE', memory.read_text())
                    self.assertEqual(agent.memory.revision, 1)
                    self.assertFalse((agent.workspace / 'TASK.md').exists())
                    self.assertTrue((agent.output / 'rollover-1/memory-before.md').exists())
                    self.assertTrue((agent.output / 'rollover-1/memory-after.md').exists())
                finally:
                    await agent.close()

    async def test_archive_failure_does_not_erase_short_or_long_memory(self):
        for arm in ('native', 'memrsi'):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as directory:
                agent = self.make(Path(directory), arm)
                try:
                    await agent.observe_only('Unarchived latest public feedback.', {})
                    memory = agent.workspace / 'memory/MEMORY.md'
                    memory.write_text('Existing mission')
                    before = copy.deepcopy(agent.loop.sessions.get_or_create(agent.session_key).messages)

                    async def fail(provider, **kwargs):
                        return LLMResponse(content='No valid archive tool call')

                    with patch.object(Provider, '_chat_attempts', fail):
                        with self.assertRaisesRegex(RuntimeError, 'native_session_archival_failed'):
                            await agent.rollover()
                    self.assertEqual(agent.loop.sessions.get_or_create(agent.session_key).messages, before)
                    self.assertEqual(memory.read_text(), 'Existing mission')
                finally:
                    await agent.close()

    async def test_guidance_recomputed_uses_latest_public_short_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = self.make(Path(directory), 'memrsi')
            try:
                await agent.observe_only('Latest public feedback: order 12 completed.', {'secret': 'PRIVATE_SENTINEL'})
                observations = []

                async def guide(messages, current):
                    observations.append((copy.deepcopy(messages), current))
                    self.assertIn('order 12 completed', json.dumps(messages))
                    self.assertNotIn('PRIVATE_SENTINEL', json.dumps(messages))
                    self.assertFalse((agent.workspace / 'TASK.md').exists())
                    return 'FRESH_GUIDANCE_' + str(len(observations))

                async def process(message, *, session_key):
                    prompt = agent.loop.context.build_system_prompt()
                    self.assertIn('FRESH_GUIDANCE_' + str(len(observations)), prompt)
                    self.assertNotIn('PRIVATE_SENTINEL', prompt)
                    await agent.action.execute('finish', 'This is a test of no programmatic veto.')
                    return 'Decision submitted.'

                with patch.object(agent.ops, 'guide', guide), patch.object(agent.loop, 'process_direct', process):
                    (agent.workspace / 'TASK.md').write_text('STALE_GUIDANCE')
                    for _ in range(2):
                        result = await agent.turn('Continue.', {'secret': 'PRIVATE_SENTINEL'}, decision=True)
                        self.assertEqual(result['skill'], 'finish')
                        self.assertFalse((agent.workspace / 'TASK.md').exists())
                self.assertEqual(len(observations), 2)
            finally:
                await agent.close()

    async def test_replay_preserves_public_action_not_private_score(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = self.make(Path(directory), 'native')
            try:
                await agent.replay_observe('Continue.', {
                    'skill': 'finish', 'reason': 'Recorded model reason.',
                    'correct': False, 'expected': 'PRIVATE_EXPECTED', 'reward': -1,
                })
                text = json.dumps(agent.loop.sessions.get_or_create(agent.session_key).messages)
                self.assertIn('Recorded model reason.', text)
                self.assertIn('finish', text)
                self.assertNotIn('PRIVATE_EXPECTED', text)
                self.assertNotIn('reward', text)
                self.assertEqual(agent.action.records, [])
                self.assertEqual(agent.provider.calls, 0)
                self.assertTrue(json.loads((agent.output / 'received-events.jsonl').read_text())['replay'])
            finally:
                await agent.close()


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lock_path = Path(directory.name) / 'model-request.lock'
        patcher = patch('model_provider.MODEL_LOCK_PATH', self.lock_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_clean_upstream_hook_independence_and_same_request_retry(self):
        class Unavailable(Exception):
            status_code = 502
            body = {'error': {'code': 'upstream_unavailable', 'retryable': True, 'output_started': False}}

        with tempfile.TemporaryDirectory() as directory:
            provider = Provider(Path(directory), api_key='LOCAL_TEST_KEY')
            good = LLMResponse(content='ok')
            provider._parse = lambda value: value
            create = AsyncMock(side_effect=[Unavailable(), good])
            try:
                with patch.object(provider._client.chat.completions, 'create', create), \
                        patch.object(CustomProvider, 'chat', side_effect=AssertionError('Do not delegate to upstream chat')), \
                        patch('model_provider.asyncio.sleep', new_callable=AsyncMock):
                    result = await provider.chat(messages=[{'role': 'user', 'content': 'Continue.'}])
                self.assertEqual(result.content, 'ok')
                self.assertEqual(create.await_count, 2)
                self.assertEqual(create.await_args_list[0].kwargs, create.await_args_list[1].kwargs)
                self.assertEqual(provider.transport_retries, 1)
                self.assertEqual(provider.calls, 2)
            finally:
                await provider._client.close()

    async def test_partial_output_is_never_retried_and_key_is_redacted(self):
        class Partial(Exception):
            status_code = 502
            body = {'error': {'code': 'upstream_interrupted', 'retryable': True, 'output_started': True}}

        with tempfile.TemporaryDirectory() as directory:
            provider = Provider(Path(directory), api_key='SECRET_FOR_TEST_REDACTION')
            create = AsyncMock(side_effect=Partial())
            try:
                with patch.object(provider._client.chat.completions, 'create', create):
                    with self.assertRaisesRegex(RuntimeError, 'provider_error'):
                        await provider.chat(messages=[{'role': 'user', 'content': 'SECRET_FOR_TEST_REDACTION'}])
                self.assertEqual(create.await_count, 1)
                for path in Path(directory).glob('*.json*'):
                    self.assertNotIn('SECRET_FOR_TEST_REDACTION', path.read_text())
                self.assertIn('[REDACTED]', (Path(directory) / 'failed-model-requests.jsonl').read_text())
            finally:
                await provider._client.close()

    async def test_concurrent_providers_admit_only_one_model_request(self):
        with tempfile.TemporaryDirectory() as directory:
            providers = [Provider(Path(directory) / str(index), api_key='LOCAL_TEST_KEY')
                         for index in range(2)]
            active = 0
            maximum = 0

            async def create(**request):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                try:
                    await asyncio.sleep(0.08)
                    return LLMResponse(content='ok')
                finally:
                    active -= 1

            try:
                for provider in providers:
                    provider._parse = lambda response: response
                with patch.object(providers[0]._client.chat.completions, 'create', AsyncMock(side_effect=create)), \
                        patch.object(providers[1]._client.chat.completions, 'create', AsyncMock(side_effect=create)):
                    responses = await asyncio.gather(*(provider.chat(messages=[{'role': 'user', 'content': 'Continue.'}])
                                                       for provider in providers))
                self.assertEqual(maximum, 1)
                self.assertEqual([response.content for response in responses], ['ok', 'ok'])
                self.assertEqual([provider.calls for provider in providers], [1, 1])
                waits = [json.loads((provider.output / 'model-admission.jsonl').read_text())['wait_seconds']
                         for provider in providers]
                self.assertGreater(max(waits), 0.05)
            finally:
                for provider in providers:
                    await provider._client.close()

    async def test_request_error_releases_cross_process_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            providers = [Provider(Path(directory) / str(index), api_key='LOCAL_TEST_KEY')
                         for index in range(2)]
            try:
                with patch.object(providers[0]._client.chat.completions, 'create', AsyncMock(side_effect=ValueError('fixture error'))):
                    with self.assertRaisesRegex(RuntimeError, 'provider_error'):
                        await providers[0].chat(messages=[{'role': 'user', 'content': 'Continue.'}])
                with self.lock_path.open('a') as external:
                    fcntl.flock(external.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(external.fileno(), fcntl.LOCK_UN)
                providers[1]._parse = lambda response: response
                with patch.object(providers[1]._client.chat.completions, 'create', AsyncMock(return_value=LLMResponse(content='ok'))):
                    response = await providers[1].chat(messages=[{'role': 'user', 'content': 'Continue.'}])
                self.assertEqual(response.content, 'ok')
            finally:
                for provider in providers:
                    await provider._client.close()

    async def test_admission_timeout_does_not_call_model_or_consume_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = Provider(Path(directory), api_key='LOCAL_TEST_KEY')
            create = AsyncMock()
            try:
                with self.lock_path.open('a') as external:
                    fcntl.flock(external.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with patch('model_provider.MODEL_ADMISSION_TIMEOUT', 0.05), \
                            patch.object(provider._client.chat.completions, 'create', create):
                        with self.assertRaisesRegex(RuntimeError, 'model_admission_wait_timeout'):
                            await provider.chat(messages=[{'role': 'user', 'content': 'Continue.'}])
                    fcntl.flock(external.fileno(), fcntl.LOCK_UN)
                create.assert_not_awaited()
                self.assertEqual(provider.calls, 0)
                self.assertEqual(provider.transport_retries, 0)
                self.assertFalse((provider.output / 'calls.json').exists())
                record = json.loads((provider.output / 'model-admission.jsonl').read_text())
                self.assertEqual(record['status'], 'wait_timeout')
                self.assertGreaterEqual(record['wait_seconds'], 0.05)
            finally:
                await provider._client.close()


if __name__ == '__main__':
    unittest.main()
