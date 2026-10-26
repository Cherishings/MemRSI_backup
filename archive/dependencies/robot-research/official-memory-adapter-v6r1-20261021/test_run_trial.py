"""Offline launcher tests: no models, GPU execution, SSH, or remote mutations."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import tempfile
import types
import unittest
from unittest import mock

import run_trial as rt


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.code = self.root / 'code'
        self.code.mkdir()
        for relative in ('run_trial.py', 'common/visual_actor.py', 'remem/pair_episode.py', 'rmbench/pair_episode.py'):
            p = self.code / relative
            p.parent.mkdir(exist_ok=True)
            p.write_text('# frozen source\n')
        (self.code / 'remem/protocol.json').write_text('{"limit": 480}')
        self.policy = self.root / 'policy.json'
        self.policy.write_text('{"update": "u", "guidance": "g"}')
        self.registry = self.root / 'attempts.json'
        self.robot = self.root / 'robot'
        self.robot.mkdir()
        (self.root / 'paos/qwen-deploy').mkdir(parents=True)
        self.patches = [mock.patch.object(rt, 'HERE', self.code), mock.patch.object(rt, 'ROBOT', self.robot)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def args(self, output='case-1', **updates):
        result = argparse.Namespace(benchmark='rmbench', phase='development', method='pre', seed=2000, gpu=2,
            policy=self.policy, ledger=self.root / 'learning.json', output=self.root / output,
            attempt_ledger=self.registry, retry_audit=None)
        for k, v in updates.items():
            setattr(result, k, v)
        return result

    def info(self, args):
        return dict(benchmark=args.benchmark, seed=args.seed, method=args.method, split=args.phase,
                    policy_sha256=rt.policy_sha(args.policy), identity={'pid': 987654321, 'start_ticks': '4'})

    def reserve(self, args):
        args.output.mkdir(exist_ok=True)
        info = self.info(args)
        with mock.patch.object(rt, 'matches_identity', return_value=False):
            rt.register_attempt(args, info)
        return info

    def technical(self, args):
        info = self.reserve(args)
        rt.write(args.output / 'result.json', {'status': 'technical_failure'})
        rt.settle_attempt(info, 'technical_failure')
        return info

    def audit(self, old):
        audit = self.root / ('audit-' + old.output.name + '.json')
        rt.write(audit, {'approved': True, 'prior_output': str(old.output.resolve()), 'reason': 'verified transport failure; all original children exited'})
        return audit

    def release(self):
        initial = rt.policy_sha(self.policy)
        data = {'gate': 'passed', 'source_hashes': rt.source_hashes(),
                'policy_hashes': {'rmbench': {'pre': initial, 'post': initial}},
                'selection': {'rmbench': {
                    'basis': 'unchanged_parent_fallback', 'initial_policy_sha256': initial,
                    'evolution_supported': False, 'new_domain_rule_adopted': False}},
                'validation': {'rmbench': None}}
        rt.write(self.code / 'release.json', data)
        return data

    def validated_release(self):
        data = self.release()
        initial = 'a' * 64
        candidate = rt.policy_sha(self.policy)
        data['policy_hashes']['rmbench']['pre'] = initial
        data['selection']['rmbench'] = {
            'basis': 'validated_candidate', 'initial_policy_sha256': initial,
            'evolution_supported': True, 'new_domain_rule_adopted': True}
        data['validation']['rmbench'] = {
            'passed': True, 'candidate_policy_sha256': candidate,
            'effect': {'split': 'validation', 'planned_pairs': 12, 'valid_pairs': 12,
                'success_gain': 0, 'new_protocol_or_capacity_failures': [],
                'by_benchmark': {'rmbench': {'pairs': 12}}}}
        rt.write(self.code / 'release.json', data)
        return data

    def test_source_manifest_requires_layout_and_includes_launcher_protocol(self):
        hashes = rt.source_hashes()
        self.assertIn('run_trial.py', hashes)
        self.assertIn('remem/protocol.json', hashes)
        (self.code / 'common/visual_actor.py').unlink()
        with self.assertRaisesRegex(ValueError, 'layout_incomplete'):
            rt.source_hashes()

    def test_frozen_gate_rejects_modified_source_or_missing_release(self):
        args = self.args(phase='test', seed=2200)
        with self.assertRaises(FileNotFoundError):
            rt.verify_release(args, rt.source_hashes())
        self.release()
        rt.verify_release(args, rt.source_hashes())
        (self.code / 'remem/protocol.json').write_text('{"limit": 999}')
        with self.assertRaisesRegex(ValueError, 'formal_release'):
            rt.verify_release(args, rt.source_hashes())

    def test_policy_hash_is_canonical_and_frozen_gate_rejects_changed_policy(self):
        args = self.args(phase='test', seed=2200)
        self.release()
        file_hash = rt.sha(self.policy)
        self.policy.write_text('{\n  "guidance":"g", "update":"u"\n}')
        self.assertNotEqual(file_hash, rt.sha(self.policy))
        rt.verify_release(args, rt.source_hashes())
        self.policy.write_text('{"guidance":"changed", "update":"u"}')
        with self.assertRaisesRegex(ValueError, 'frozen_test_policy'):
            rt.verify_release(args, rt.source_hashes())

    def test_unchanged_parent_fallback_runs_without_passed_reserved_validation(self):
        for validation in (None, {'passed': False, 'candidate_policy_sha256': 'b' * 64}):
            data = self.release()
            data['validation']['rmbench'] = validation
            rt.write(self.code / 'release.json', data)
            for method in ('native', 'post'):
                rt.verify_release(self.args(phase='test', seed=2200, method=method), rt.source_hashes())

    def test_fallback_rejects_changed_initial_or_candidate_and_evolution_claim(self):
        changes = (
            lambda d: d['selection']['rmbench'].pop('initial_policy_sha256'),
            lambda d: d['selection']['rmbench'].update(initial_policy_sha256='b' * 64),
            lambda d: d['policy_hashes']['rmbench'].update(post='b' * 64),
            lambda d: d['selection']['rmbench'].update(evolution_supported=True),
            lambda d: d['selection']['rmbench'].update(new_domain_rule_adopted=True),
        )
        for change in changes:
            data = self.release()
            change(data)
            rt.write(self.code / 'release.json', data)
            for method in ('native', 'post'):
                with self.assertRaisesRegex(ValueError, 'formal_release'):
                    rt.verify_release(self.args(phase='test', seed=2200, method=method), rt.source_hashes())

    def test_validated_candidate_requires_reserved_pass_and_matching_hash(self):
        args = self.args(phase='test', seed=2200, method='post')
        self.validated_release()
        rt.verify_release(args, rt.source_hashes())
        changes = (
            lambda d: d['validation']['rmbench'].update(passed=False),
            lambda d: d['validation']['rmbench'].update(passed='true'),
            lambda d: d['validation']['rmbench'].update(candidate_policy_sha256='b' * 64),
            lambda d: d['validation']['rmbench']['effect'].update(split='development'),
            lambda d: d['validation']['rmbench']['effect'].update(valid_pairs=11),
            lambda d: d['validation']['rmbench']['effect'].update(success_gain=-1),
            lambda d: d['validation']['rmbench']['effect'].update(new_protocol_or_capacity_failures=[{'status': 'capacity_failure'}]),
            lambda d: d['selection']['rmbench'].update(new_domain_rule_adopted=False),
        )
        for change in changes:
            data = self.validated_release()
            change(data)
            rt.write(self.code / 'release.json', data)
            with self.assertRaisesRegex(ValueError, 'reserved_gate'):
                rt.verify_release(args, rt.source_hashes())

    def test_unknown_selection_basis_blocks_native_and_mem_formal_execution(self):
        data = self.release()
        data['selection']['rmbench']['basis'] = 'unreviewed_candidate'
        rt.write(self.code / 'release.json', data)
        for method in ('native', 'post'):
            with self.assertRaisesRegex(ValueError, 'selection_basis'):
                rt.verify_release(self.args(phase='test', seed=2200, method=method), rt.source_hashes())

    def test_new_output_cannot_reset_attempt(self):
        old = self.args()
        self.technical(old)
        with self.assertRaisesRegex(ValueError, 'retry_audit_required'):
            self.reserve(self.args(output='different-directory'))

    def test_audited_technical_retry_increments_and_caps_at_three(self):
        old = self.args()
        self.technical(old)
        for attempt in (2, 3):
            new = self.args(output='case-' + str(attempt), retry_audit=self.audit(old))
            info = self.technical(new)
            self.assertEqual(info['attempt'], attempt)
            self.assertEqual(len(info['previous_attempts']), attempt - 1)
            old = new
        with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
            self.reserve(self.args(output='case-4', retry_audit=self.audit(old)))

    def test_capability_failure_cannot_be_retried_even_with_audit(self):
        old = self.args()
        info = self.reserve(old)
        rt.write(old.output / 'result.json', {'status': 'task_failure'})
        rt.settle_attempt(info, 'task_failure')
        with self.assertRaisesRegex(ValueError, 'retry_forbidden'):
            self.reserve(self.args(output='case-2', retry_audit=self.audit(old)))

    def test_live_previous_launcher_or_child_blocks_retry(self):
        old = self.args()
        self.technical(old)
        new = self.args(output='case-2', retry_audit=self.audit(old))
        new.output.mkdir()
        with mock.patch.object(rt, 'matches_identity', return_value=True):
            with self.assertRaisesRegex(ValueError, 'process_still_alive'):
                rt.register_attempt(new, self.info(new))
        rt.write(old.output / 'child-processes.json', [{'identity': {'pid': 100, 'start_ticks': '1'}}])
        with mock.patch.object(rt, 'matches_identity', side_effect=[False, True]):
            with self.assertRaisesRegex(ValueError, 'child_still_alive'):
                rt.register_attempt(new, self.info(new))

    def test_exhausted_learning_ledger_is_not_reset(self):
        ledger = self.root / 'learning.json'
        rt.write(ledger, {'inherited_used': 8986, 'used': 9745, 'authorized_limit': 9745, 'entries': []})
        before = ledger.read_bytes()
        self.assertFalse(rt.learning_budget_available(ledger))
        self.assertEqual(ledger.read_bytes(), before)

    def test_unauthorized_limit_increase_rejected(self):
        ledger = self.root / 'learning.json'
        rt.write(ledger, {'inherited_used': 8986, 'used': 9745, 'authorized_limit': 20000})
        with self.assertRaisesRegex(ValueError, 'authorization_missing'):
            rt.learning_budget_available(ledger)

    def test_learning_pause_preserves_actor_result_and_is_unscored(self):
        args = self.args()
        info = self.reserve(args)
        raw = {'status': 'technical_failure', 'error_type': 'LearningBudgetExhausted', 'steps': 77}
        rt.write(args.output / 'result.json', raw)
        result = rt.record_outcome(args.output, raw, info)
        self.assertEqual(result['status'], 'paused_learning_budget')
        self.assertEqual(json.loads((args.output / 'actor-result.json').read_text()), raw)
        self.assertFalse((args.output / 'scored-record.json').exists())
        self.assertFalse((args.output / 'trial-complete.json').exists())
        self.assertTrue((args.output / 'trial-paused.json').exists())
        self.assertFalse(result['simulator_state_checkpointed'])

    def test_explicit_actor_pause_and_episode_budget_distinct(self):
        self.assertTrue(rt.is_learning_pause({'status': 'paused_learning_budget'}, 'development'))
        self.assertFalse(rt.is_learning_pause({'status': 'agent_failure', 'error_code': 'agent_call_budget_exhausted'}, 'development'))
        self.assertFalse(rt.is_learning_pause({'error_type': 'LearningBudgetExhausted'}, 'test'))

    def test_scored_projection_has_split_and_canonical_hash(self):
        args = self.args()
        info = self.reserve(args)
        result = {'status': 'agent_failure', 'error_code': 'active_context_budget_exceeded'}
        rt.record_outcome(args.output, result, info)
        row = json.loads((args.output / 'scored-record.json').read_text())
        self.assertEqual(set(row), {'benchmark', 'seed', 'method', 'split', 'status', 'official_success', 'policy_sha256'})
        self.assertEqual(row['split'], 'development')
        self.assertEqual(row['status'], 'capacity_failure')
        self.assertEqual(row['policy_sha256'], rt.policy_sha(self.policy))

    def test_unknown_agent_error_stays_unclassified(self):
        self.assertEqual(rt.normalized_status({'status': 'agent_failure', 'error_code': 'mysterious'}), 'unclassified_failure')
        self.assertEqual(rt.normalized_status({'status': 'policy_failure'}), 'task_failure')
        self.assertEqual(rt.normalized_status({'status': 'agent_failure', 'error_code': 'guidance_grounding_failure'}), 'protocol_failure')
        self.assertEqual(rt.normalized_status({'status': 'agent_failure', 'error_code': 'agent_call_budget_exhausted'}), 'budget_failure')

    def test_ready_file_must_belong_to_spawned_process(self):
        path = self.root / 'ready.json'
        rt.write(path, {'pid': 100, 'start_ticks': 'old'})
        child = mock.Mock(pid=100, _trial_identity={'pid': 100, 'start_ticks': 'new'})
        child.poll.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'identity_mismatch'):
            rt.ready(path, child)

    def test_stop_refuses_pid_reuse_and_does_not_signal(self):
        child = mock.Mock(pid=100, _trial_identity={'pid': 100, 'start_ticks': 'old'})
        child.poll.return_value = None
        with mock.patch.object(rt, 'matches_identity', return_value=False), mock.patch.object(rt.os, 'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError, 'identity_changed'):
                rt.stop(child)
            kill.assert_not_called()

    def test_stop_only_signals_dedicated_owned_group(self):
        child = mock.Mock(pid=100, _trial_identity={'pid': 100, 'start_ticks': 'old'})
        child.poll.return_value = None
        with mock.patch.object(rt, 'matches_identity', return_value=True), mock.patch.object(rt.os, 'getpgid', return_value=100), mock.patch.object(rt.os, 'killpg') as kill:
            rt.stop(child)
            kill.assert_called_once_with(100, signal.SIGTERM)
            child.wait.assert_called_once_with(timeout=10)

    def test_budget_preflight_never_acquires_gpu_or_starts_attempt(self):
        args = self.args()
        rt.write(args.ledger, {'inherited_used': 8986, 'used': 9745, 'authorized_limit': 9745})
        with mock.patch.dict('sys.modules', {'setproctitle': types.SimpleNamespace(setproctitle=lambda _: None)}), mock.patch.object(rt.subprocess, 'Popen') as popen, mock.patch.object(rt.subprocess, 'check_output') as gpu:
            rt.run(args)
        popen.assert_not_called()
        gpu.assert_not_called()
        self.assertFalse((args.output / 'started.json').exists())
        self.assertFalse((args.output / 'result.json').exists())
        self.assertTrue((args.output / 'waiting-learning-budget.json').exists())

    def test_partial_remaining_budget_waits_without_using_gpu(self):
        args = self.args()
        rt.write(args.ledger, {'inherited_used': 8986, 'used': 9266, 'authorized_limit': 9745})
        with mock.patch.dict('sys.modules', {'setproctitle': types.SimpleNamespace(setproctitle=lambda _: None)}), mock.patch.object(rt.subprocess, 'Popen') as popen, mock.patch.object(rt.subprocess, 'check_output') as gpu:
            rt.run(args)
        self.assertFalse((args.output / 'started.json').exists())
        self.assertFalse((args.output / 'result.json').exists())
        waiting = json.loads((args.output / 'waiting-learning-budget.json').read_text())
        self.assertEqual(waiting['remaining'], 479)
        self.assertEqual(waiting['required_episode_capacity'], 480)
        popen.assert_not_called()
        gpu.assert_not_called()

    def test_admission_lock_is_held_through_episode_scope_and_released(self):
        args = self.args()
        args.output.mkdir()
        lock_path = args.ledger.with_suffix('.admission.lock')
        with rt.learning_admission(args) as admitted:
            self.assertTrue(admitted)
            self.assertIsInstance(args._learning_admission_fd, int)
            with lock_path.open('a') as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertFalse(hasattr(args, '_learning_admission_fd'))
        with lock_path.open('a') as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_test_phase_does_not_touch_learning_admission_lock(self):
        args = self.args(phase='test', ledger=None)
        with rt.learning_admission(args) as admitted:
            self.assertTrue(admitted)
        self.assertFalse((self.root / 'learning.admission.lock').exists())

    def test_interrupted_actor_cleans_all_owned_children_and_records_technical(self):
        args = self.args()
        args.output.mkdir()
        children = []
        def spawn(command, filename, child_env, gpu_lock):
            child = mock.Mock(pid=100 + len(children))
            child._trial_identity = {'pid': child.pid, 'start_ticks': '1'}
            if filename == 'actor.private.log':
                child.wait.side_effect = InterruptedError('launcher_interrupted')
            children.append(child)
            return child
        with mock.patch.object(rt.subprocess, 'check_output', return_value='0'), mock.patch.object(rt, 'ready'), mock.patch.object(rt, 'stop') as stop:
            rt._run_admitted(args, rt.source_hashes(), 'memrsi', self.code / 'rmbench', {}, spawn)
        self.assertEqual(len(children), 3)
        self.assertEqual([call.args[0] for call in stop.call_args_list], list(reversed(children)))
        result = json.loads((args.output / 'result.json').read_text())
        self.assertEqual(result['status'], 'technical_failure')
        self.assertEqual(result['error_type'], 'InterruptedError')
        self.assertEqual(json.loads((args.output / 'scored-record.json').read_text())['status'], 'technical_failure')

    def test_formal_test_strips_inherited_learning_environment(self):
        args = self.args(phase='test', seed=2200, method='native')
        self.release()
        captured = {}
        def admitted(args, hashes, arm, bench, env, spawn):
            captured.update(env)
        with mock.patch.dict('sys.modules', {'setproctitle': types.SimpleNamespace(setproctitle=lambda _: None)}), mock.patch.dict(rt.os.environ, {'MEMRSI_LEARNING_LEDGER': '/wrong', 'MEMRSI_PHASE': 'development', 'MEMRSI_CASE_ID': 'other'}), mock.patch.object(rt, '_run_admitted', side_effect=admitted):
            rt.run(args)
        self.assertFalse(any(key in captured for key in ('MEMRSI_LEARNING_LEDGER', 'MEMRSI_PHASE', 'MEMRSI_CASE_ID')))

    def test_source_manifest_ignores_pointer_and_release_but_includes_root_python(self):
        baseline = rt.source_hashes()
        rt.write(self.code / 'latest.json', {'pid': 1})
        rt.write(self.code / 'release.json', {'gate': 'new'})
        self.assertEqual(rt.source_hashes(), baseline)
        (self.code / 'run_study.py').write_text('# coordinator')
        self.assertIn('run_study.py', rt.source_hashes())

    def test_existing_output_is_rechecked_after_trial_lock(self):
        args = self.args()
        args.output.mkdir()
        rt.write(args.output / 'result.json', {'status': 'success'})
        with mock.patch.dict('sys.modules', {'setproctitle': types.SimpleNamespace(setproctitle=lambda _: None)}), mock.patch.object(rt.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(ValueError, 'must_not_be_rerun'):
                rt.run(args)
        popen.assert_not_called()

    def test_held_trial_lock_refuses_duplicate_launcher(self):
        args = self.args()
        args.output.mkdir()
        with (args.output / 'trial.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.dict('sys.modules', {'setproctitle': types.SimpleNamespace(setproctitle=lambda _: None)}):
                with self.assertRaises(BlockingIOError):
                    rt.run(args)


if __name__ == '__main__':
    unittest.main()
