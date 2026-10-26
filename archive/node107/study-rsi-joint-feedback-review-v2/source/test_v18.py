import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from targeted_probe import select
from targeted_pilot import bootstrap_pilot
from targeted_pipeline import make_runner


class V18Tests(unittest.TestCase):
    def test_small_ceiling_gain_advances_but_tie_does_not(self):
        rows = []
        for i in range(21):
            for name in ('parent', 'candidate'):
                rows.append(dict(fixture=str(i // 3), repeat=i % 3, policy=name,
                                 status='answered', correct=i < (19 if name == 'parent' else 20),
                                 all_costs_known=True, all_attempt_calls=3, all_attempt_cost_tokens=10))
        self.assertTrue(select(rows)['accepted'])
        for row in rows:
            if row['policy'] == 'candidate' and row['fixture'] == '6' and row['repeat'] == 1:
                row['correct'] = False
        self.assertFalse(select(rows)['accepted'])

    def test_authorized_six_gpu_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            def runner(directory, stop, gpus):
                self.assertTrue(directory.is_dir())
                self.assertEqual(gpus, (0, 1, 2, 3, 4, 5))
                return gpus
            with patch('targeted_pipeline.PhysicalRunner', runner):
                make_runner(tmp, None, range(6))

    def test_pilot_reuse_keeps_budget_excludes_selection_and_cycle1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);src = root / 'pilot';out = root / 'new/learning'
            src.mkdir();out.parent.mkdir()
            def write(path, obj):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(obj))
            pointer = root / 'pointer.json'
            write(pointer, dict(result=str(src), coordinator=dict(pid=1, start_ticks='0')))
            write(src / 'report.json', dict(status='learning_finished_no_qualified_policy'))
            write(src / 'learning/report.json', dict(promotions=0))
            write(src / 'learning/learning-call-ledger.json', dict(calls=2972, limit=6000))
            for name in ('budget.json', 'selected-orders.json'):
                write(src / name, {});write(out.parent / name, {})
            names = ['diagnoses', 'guidance/proposal', 'guidance/critic', 'guidance/probes',
                     'update/proposal', 'update/critic', 'update/probes']
            for name in names:
                write(src / 'learning/cycle-0' / name / 'value.json', {'evidence': 1})
            write(src / 'learning/cycle-0/selection.json', {'accepted': False})
            write(src / 'learning/cycle-1/selection.json', {'accepted': False})
            with patch('targeted_pilot.same_process', return_value=False):
                bootstrap_pilot(pointer, out)
                self.assertEqual(json.loads((out / 'learning-call-ledger.json').read_text())['calls'], 2972)
                self.assertFalse((out / 'cycle-0/selection.json').exists())
                self.assertFalse((out / 'cycle-1').exists())
                # Resume must never reset a subsequently increased ledger.
                write(out / 'learning-call-ledger.json', dict(calls=3000, limit=6000))
                bootstrap_pilot(pointer, out)
                self.assertEqual(json.loads((out / 'learning-call-ledger.json').read_text())['calls'], 3000)


if __name__ == '__main__':
    unittest.main()
