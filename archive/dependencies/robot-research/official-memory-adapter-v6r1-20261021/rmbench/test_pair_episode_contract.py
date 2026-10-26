"""Exercise the real episode loop with deterministic CPU-only RPC doubles."""
import asyncio
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from frozen_executor import ExecutionLifecycle
from test_execution_lifecycle import FakeAgent
import pair_episode


class EpisodeFixture:
    def __init__(self, output, horizon, flags=(), instructions=None, finish_at=None,
                 budget_error=False):
        self.output, self.horizon, self.steps = output, horizon, 0
        self.agent = FakeAgent(flags)
        self.lifecycle = ExecutionLifecycle(self.agent)
        self.request_steps, self.actor_inputs, self.executed = [], [], []
        self.instructions = instructions or ['cover red']
        self.finish_at, self.budget_error = finish_at, budget_error
        self.provider = types.SimpleNamespace(calls=0, wire_attempts=0, transport_retries=0)
        self.controller_history = []

    def public(self):
        return {'steps': self.steps, 'horizon': self.horizon, 'instruction': 'Cover the blocks.',
                'cameras': [], 'proprio': {}}

    def post(self, port, method, payload):
        if method == 'reset':
            return {'status': 'reset'}
        if method == 'observe':
            return {'public': self.public()}
        if method == 'step':
            assert len(payload['actions']) == 1
            self.steps += 1
            self.executed.append(self.steps)
            return {'public': self.public(), 'evaluator': {
                'done': self.steps >= self.horizon, 'success': False}}
        if method == 'close':
            (self.output / 'simulator').mkdir(exist_ok=True)
            (self.output / 'simulator/result.json').write_text(json.dumps({
                'status': 'task_failure', 'official_check_success': False, 'steps': self.steps}))
            return {'closed': True}
        raise AssertionError(method)

    def predict(self, port, public, instruction, new_subtask=False):
        actions = self.lifecycle.predict({'step': public['steps']}, instruction, new_subtask)
        self.controller_history.append((public['steps'], instruction, new_subtask))
        return {'actions': actions[:, :14].tolist(), 'controller': {'mock': True}}

    def observe_step(self, port, public):
        # This verifies the scheduler supplies the post-action public packet,
        # instead of repeating the previous observation or doing two updates.
        assert public['steps'] == self.steps
        return self.lifecycle.observe_step({'step': public['steps']})

    def actor_class(self):
        fixture = self

        class Actor:
            def __init__(self, *args, **kwargs):
                self.provider = fixture.provider

            async def choose(self, text, cameras, proprio):
                if fixture.budget_error:
                    raise RuntimeError('learning_budget_exhausted')
                fixture.request_steps.append(fixture.steps)
                fixture.actor_inputs.append((text, cameras, proprio))
                self.provider.calls += 1
                self.provider.wire_attempts += 1
                if fixture.finish_at is not None and fixture.steps >= fixture.finish_at:
                    return {'skill': 'finish', 'instruction': '', 'reason': 'visible claim'}
                index = min(len(fixture.request_steps) - 1, len(fixture.instructions) - 1)
                return {'skill': 'execute', 'instruction': fixture.instructions[index], 'reason': 'continue', 'continuity': ('start' if len(fixture.request_steps)==1 else 'replace' if fixture.instructions[index] != fixture.instructions[max(0,index-1)] else 'continue')}

            async def observe(self, text):
                fixture.actor_inputs.append((text, None, None))

            async def close(self):
                pass

        return Actor

    def run(self):
        args = types.SimpleNamespace(arm='native', seed=1200, output=self.output,
            policy=self.output / 'unused.json', controller_port=1, simulator_port=2,
            simulator_output=self.output / 'simulator')
        modules = {
            'setproctitle': types.SimpleNamespace(setproctitle=lambda x: None),
            'rmb_visual_actor': types.SimpleNamespace(RMBVisualAgent=self.actor_class()),
            'rpc_client': types.SimpleNamespace(post=self.post, predict=self.predict,
                observe_step=self.observe_step, decode_cameras=lambda public: []),
            'runtime_config': types.SimpleNamespace(usage_totals=lambda output: {}),
        }
        with patch.dict('sys.modules', modules):
            asyncio.run(pair_episode.run(args))
        return json.loads((self.output / 'result.json').read_text())


class PairEpisodeContractTests(unittest.TestCase):
    def test_macro_segments_preserve_cache_and_observe_every_step(self):
        with tempfile.TemporaryDirectory() as folder:
            f = EpisodeFixture(Path(folder), horizon=70)
            result = f.run()
            self.assertEqual(f.request_steps, [0, 32, 64])
            self.assertEqual(f.agent.observations, list(range(71)))
            self.assertEqual(f.executed, list(range(1, 71)))
            self.assertEqual(f.lifecycle.semantic_resets, 0)
            self.assertEqual(result['steps'], 70)
            self.assertEqual(result['planned_decisions_max'], 70)

    def test_post_action_boundary_replans_without_one_extra_action(self):
        with tempfile.TemporaryDirectory() as folder:
            f = EpisodeFixture(Path(folder), horizon=36, flags=[False, True, True])
            result = f.run()
            self.assertEqual(f.request_steps, [0, 2, 34])
            self.assertEqual(f.agent.observations[:5], [0, 1, 2, 2, 3])
            self.assertEqual(f.lifecycle.semantic_resets, 1)
            self.assertEqual(result['steps'], 36)

    def test_explicit_language_change_resets_once_at_semantic_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            f = EpisodeFixture(Path(folder), horizon=64, instructions=['cover red', 'cover blue'])
            f.run()
            self.assertEqual(f.lifecycle.semantic_resets, 1)
            self.assertEqual([p for p in f.controller_history if p[2]], [(32, 'cover blue', True)])

    def test_finish_is_not_vetoed_by_hidden_environment_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            f = EpisodeFixture(Path(folder), horizon=70, finish_at=32)
            result = f.run()
            self.assertEqual(result['stop_reason'], 'actor_finish')
            self.assertEqual(result['status'], 'task_failure')
            self.assertEqual(result['steps'], 32)
            self.assertEqual(f.lifecycle.observation_updates, 33)
            self.assertFalse(any('official_check_success' in text for text, _, _ in f.actor_inputs))

    def test_cumulative_budget_pause_not_capability_or_retry_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            f = EpisodeFixture(Path(folder), horizon=70, budget_error=True)
            with patch.dict('os.environ', {'MEMRSI_PHASE': 'development', 'MEMRSI_LEARNING_LEDGER': 'not-read-by-test'}):
                result = f.run()
            self.assertEqual(result['status'], 'paused_learning_budget')
            self.assertEqual(result['split'], 'development')
            self.assertTrue(result['learning_ledger_configured'])
            self.assertEqual(f.steps, 0)

    def test_rpc_encodes_only_allowed_current_observation_fields(self):
        path = Path(__file__).with_name('rpc_client.py')
        spec = importlib.util.spec_from_file_location('actual_rpc', path)
        rpc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rpc)
        captured = []
        rpc.post = lambda port, method, payload: captured.append((method, payload))
        public = {'cameras': [{'rgb_base64': 'AAAA', 'shape': [1, 1, 3]}],
                  'proprio': {'joint_action': [0] * 14}, 'steps': 9,
                  'evaluator': {'success': True}, 'hidden_object_pose': [9, 9, 9]}
        rpc.predict(1, public, 'cover red', new_subtask=True)
        rpc.observe_step(1, public)
        self.assertEqual(set(captured[0][1]), {'rgb_base64', 'rgb_shape', 'joint_state', 'instruction', 'new_subtask'})
        self.assertEqual(set(captured[1][1]), {'rgb_base64', 'rgb_shape', 'joint_state'})


if __name__ == '__main__':
    unittest.main()
