"""Targeted safety/layout tests without creating random controller outputs."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from frozen_executor import env14_to_model16, model16_to_env14, FrozenRMBenchExecutor, UPSTREAM


class ContractTests(unittest.TestCase):
    def test_layout_matches_official_padding_and_permutation(self):
        sys.path.insert(0, str(UPSTREAM))
        from scripts.tools_for_deploy.layout_utils import env_to_model_layout, model_to_env_layout
        state = np.arange(14, dtype=np.float32) / 10
        native16 = np.zeros(16, dtype=np.float32)
        native16[:6], native16[7], native16[8:14], native16[15] = state[:6], state[6], state[7:13], state[13]
        official_model = env_to_model_layout(native16)
        np.testing.assert_array_equal(env14_to_model16(state), official_model)
        restored = model_to_env_layout(official_model)
        official_packed = np.concatenate([restored[:6], restored[7:8], restored[8:14], restored[15:16]])
        np.testing.assert_array_equal(model16_to_env14(official_model), official_packed)
        np.testing.assert_array_equal(official_packed, state)

    def test_bad_state_rejected(self):
        for state in [np.zeros(16), np.full(14, np.nan), np.zeros((1, 14))]:
            with self.assertRaises(ValueError):
                env14_to_model16(state)

    def test_random_weight_fallback_forbidden(self):
        with self.assertRaises(FileNotFoundError):
            FrozenRMBenchExecutor(checkpoint='/nonexistent/public-checkpoint.pt')

    def test_no_planner_construction(self):
        source = Path(__file__).with_name('frozen_executor.py').read_text()
        self.assertNotIn('MemoryMattersAgent(', source)
        self.assertNotIn('MemoryMattersPlanner(', source)

    def test_capacity_and_agent_failures_are_not_retryable_transport(self):
        from failure_classification import AGENT_ERRORS, classify
        for code in AGENT_ERRORS:
            self.assertEqual(classify(RuntimeError(code), 'actor'), ('agent_failure', code))
        self.assertEqual(classify(RuntimeError('provider_error'), 'actor')[0], 'technical_failure')
        self.assertEqual(classify(RuntimeError('unexpected'), 'actor')[0], 'unclassified_failure')


if __name__ == '__main__':
    unittest.main()
