"""Launcher guards with mocked process creation; no remote/model/GPU calls."""
import argparse
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import start_studies as launcher


class StartStudiesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.qualification = self.root / 'qualified.json'
        self.hashes = {'run_study.py': 'frozen'}
        self.qualification.write_text(json.dumps({'passed': True, 'source_hashes': self.hashes}))
        self.args = argparse.Namespace(rmbench_gpu=0, remem_gpu=1, ledger=self.root / 'ledger.json',
                                      qualification=self.qualification, output=self.root / 'studies')
        self.patches = [mock.patch.object(launcher, 'HERE', self.root / 'code'),
                        mock.patch.object(launcher.run_trial, 'source_hashes', return_value=self.hashes),
                        mock.patch.object(launcher.run_trial, 'learning_budget_remaining', return_value=759)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def test_same_gpu_rejected_without_spawning(self):
        self.args.remem_gpu = self.args.rmbench_gpu
        with mock.patch.object(launcher.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'distinct_gpus'):
                launcher.run(self.args)
        spawn.assert_not_called()
        self.assertFalse(self.args.output.exists())

    def test_unqualified_or_changed_sources_cannot_launch(self):
        for passed, hashes in [('yes', self.hashes), (True, {'run_study.py': 'changed'})]:
            with self.subTest(passed=passed, hashes=hashes):
                self.qualification.write_text(json.dumps({'passed': passed, 'source_hashes': hashes}))
                with mock.patch.object(launcher.subprocess, 'Popen') as spawn:
                    with self.assertRaisesRegex(ValueError, 'qualification'):
                        launcher.run(self.args)
                spawn.assert_not_called()
        self.assertFalse(self.args.output.exists())

    def test_insufficient_budget_causes_zero_launches(self):
        with mock.patch.object(launcher.run_trial, 'learning_budget_remaining', return_value=479), mock.patch.object(launcher.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'insufficient_authorized'):
                launcher.run(self.args)
        spawn.assert_not_called()
        self.assertFalse(self.args.output.exists())

    def test_live_pointers_prevent_duplicates_and_environment_pins_provider(self):
        processes = [mock.Mock(pid=500), mock.Mock(pid=501)]
        with mock.patch.object(launcher.subprocess, 'Popen', side_effect=processes) as spawn, mock.patch.object(launcher.run_trial, 'identity', side_effect=lambda pid: {'pid': pid, 'start_ticks': '7'}), mock.patch.object(launcher.run_trial, 'matches_identity', return_value=True), mock.patch.dict(launcher.os.environ, {'MEMRSI_FROZEN_CORE': '/stale', 'MEMRSI_LEARNING_LEDGER': '/stale-ledger'}):
            first = launcher.run(self.args)
            second = launcher.run(self.args)
        self.assertEqual(len(first['started']), 2)
        self.assertEqual(second['started'], [])
        self.assertEqual(spawn.call_count, 2)
        for call in spawn.call_args_list:
            env = call.kwargs['env']
            paths = env['PYTHONPATH'].split(':')
            self.assertIn(str(launcher.CORE), paths)
            self.assertIn(str(launcher.PAOS_ROOT), paths)
            self.assertIn(str(launcher.ROBOT / 'official-memory-common-20261017/deps'), paths)
            self.assertTrue(any(path.endswith('/actor-deps') for path in paths))
            self.assertEqual(env['MEMRSI_FROZEN_CORE'], str(launcher.CORE))
            self.assertNotIn('MEMRSI_LEARNING_LEDGER', env)

    def test_study_lock_blocks_duplicate_even_without_pointer(self):
        rm = self.args.output / 'rmbench'
        re = self.args.output / 'remem'
        rm.mkdir(parents=True)
        re.mkdir()
        (re / 'study-complete.json').write_text('{}')
        with (rm / 'study.lock').open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(launcher.subprocess, 'Popen') as spawn:
                result = launcher.run(self.args)
        spawn.assert_not_called()
        self.assertEqual(result['started'], [])
        self.assertIn({'benchmark': 'rmbench', 'reason': 'study_lock_held'}, result['skipped'])


if __name__ == '__main__':
    unittest.main()
