"""Contract regressions for real-step feedback and semantic state boundaries."""
import types
import unittest

import numpy as np

from frozen_executor import ExecutionLifecycle, _ExecutionState, env14_to_model16, model16_to_env14


class FakeMemory:
    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1


class FakeAgent:
    def __init__(self, flags=()):
        self.executor = types.SimpleNamespace(memory_bank=FakeMemory())
        self.action_count = self.end_signal_count = self.iter = self.stage = 0
        self.flags = iter(flags)
        self.observations = []
        self.forecasts = []
        self.prediction_calls = 0

    def update_obs(self, payload):
        self.observations.append(payload['step'])
        self.action_count += 1
        self.end_signal_count += int(next(self.flags, False))

    def get_action(self):
        self.prediction_calls += 1
        return {'normalized_actions': np.full((1, 30, 16), self.observations[-1], dtype=np.float32)}

    def accumulate_actions_chunk(self, actions):
        self.forecasts.append((self.iter, actions.copy()))

    def get_smoothed_actions(self, start, length):
        return self.forecasts[-1][1][0, :length].copy()


class ExecutionContractTests(unittest.TestCase):
    def test_physical_feedback_refreshes_cache_without_extra_initial_update(self):
        a = FakeAgent(); ctl = ExecutionLifecycle(a)
        ctl.predict({'step': 0}, 'cover red')
        for step in range(1, 9):
            ctl.observe_step({'step': step})
        out = ctl.predict({'step': 8}, 'cover red')
        self.assertEqual(a.observations, list(range(9)))
        self.assertEqual(a.executor.memory_bank.resets, 0)
        self.assertEqual(a.prediction_calls, 2)
        self.assertTrue(np.all(out == 8))
        self.assertEqual(a.iter, 8)

    def test_missing_step_feedback_is_rejected_instead_of_silent_chunk_prediction(self):
        ctl = ExecutionLifecycle(FakeAgent())
        ctl.predict({'step': 0}, 'cover red')
        with self.assertRaisesRegex(ValueError, 'executed_step_observations'):
            ctl.predict({'step': 8}, 'cover red')

    def test_learned_boundary_discards_only_unexecuted_predictions(self):
        a = FakeAgent([False, True, True]); ctl = ExecutionLifecycle(a)
        ctl.predict({'step': 0}, 'cover red')
        first = ctl.observe_step({'step': 1})
        second = ctl.observe_step({'step': 2})
        self.assertFalse(first['boundary_ready'])
        self.assertTrue(second['boundary_ready'])
        self.assertEqual(second['executed_steps'], 2)
        self.assertEqual(second['pending_steps'], 0)
        self.assertEqual(a.iter, 8)  # Upstream deploy_policy prediction clock.
        with self.assertRaisesRegex(ValueError, 'without_pending'):
            ctl.observe_step({'step': 3})
        ctl.predict({'step': 2}, 'cover blue')
        self.assertEqual(a.executor.memory_bank.resets, 1)
        self.assertEqual(a.end_signal_count, 0)
        self.assertEqual(a.action_count, 1)
        self.assertEqual(a.observations, [0, 1, 2, 2])

    def test_same_text_after_boundary_is_new_semantic_attempt(self):
        a = FakeAgent([False, True, True]); ctl = ExecutionLifecycle(a)
        ctl.predict({'step': 0}, 'cover red')
        ctl.observe_step({'step': 1}); ctl.observe_step({'step': 2})
        ctl.predict({'step': 2}, 'cover red')
        self.assertEqual(a.executor.memory_bank.resets, 1)
        self.assertEqual(ctl.semantic_resets, 1)

    def test_language_change_requires_explicit_semantic_boundary(self):
        a = FakeAgent(); ctl = ExecutionLifecycle(a)
        ctl.predict({'step': 0}, 'cover red')
        for step in range(1, 9): ctl.observe_step({'step': step})
        with self.assertRaisesRegex(ValueError, 'semantic_boundary'):
            ctl.predict({'step': 8}, 'cover blue')
        ctl.predict({'step': 8}, 'cover blue', new_subtask=True)
        self.assertEqual(a.executor.memory_bank.resets, 1)

    def test_joint_and_gripper_mapping_is_unchanged(self):
        state = np.arange(14, dtype=np.float32)
        model = env14_to_model16(state)
        self.assertEqual(model[6], 0)
        self.assertEqual(model[13], 0)
        self.assertEqual(model[14], state[6])
        self.assertEqual(model[15], state[13])
        np.testing.assert_array_equal(model16_to_env14(model), state)

    def test_borrowed_methods_have_no_planner_constructor(self):
        class Source:
            def __init__(self): raise AssertionError('planner constructor must not run')
            def update_obs(self, x): return ('source', x)
            def get_action(self): return 'action'
            def accumulate_actions_chunk(self, x): return x
            def get_smoothed_actions(self, x, y): return (x, y)
        state = _ExecutionState('executor', Source, 8)
        self.assertIs(state.update_obs.__func__, Source.update_obs)
        self.assertEqual(state.update_obs(1), ('source', 1))
        self.assertFalse(hasattr(state, 'high_model'))


if __name__ == '__main__':
    unittest.main()
