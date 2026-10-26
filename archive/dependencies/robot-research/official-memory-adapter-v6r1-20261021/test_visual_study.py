"""Offline integration tests: complete manifests, no GPU or provider requests."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import learn_visual as learn
import run_study as study
from adaptation_protocol import SPLITS
from learning_budget import charge
from visual_rule_proposal import (policy_sha256, validate_and_apply_proposal,
                                 build_proposal_request)


STAMP = {'root': 'offline-frozen-code'}
NATIVE = 'a' * 64


def parent_policy():
    return {'schema': 1, 'guidance': json.dumps({'kind': 'procedure_guidance_v2',
        'procedure': 'Select relevant evidence fragments. Include the current request and task identity. '
        'Remember that stored observations can be uncertain. Select no more than five source fragments.'}),
        'update': json.dumps({'kind': 'procedure_update_v2',
        'procedure': 'Preserve pending requirements. Keep the identity of distinct requests, changed priorities, '
        'and progress supported by public feedback. Compress irrelevant history while retaining unresolved work.'})}


def edit(second=False):
    return {'operator': 'update',
        'anchor': 'Keep the identity of distinct requests' if second else 'Preserve pending requirements.',
        'replacement': 'Keep distinct evidence identities and unresolved requirements' if second else
        'Preserve unresolved requirements and the uncertainty of supporting observations.',
        'rationale': 'Public progress evidence distinguishes claims from verified effects.',
        'evidence_case_ids': ['remem-2000']}


class VisualStudyIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.parent = parent_policy(); self.parent_hash = policy_sha256(self.parent)
        self.first = validate_and_apply_proposal(self.parent, edit(), ['remem-2000'], self.parent_hash)
        self.second = validate_and_apply_proposal(self.first['candidate_policy'], edit(True),
            ['remem-2000'], self.first['candidate_policy_sha256'])
        self.hashes = [self.parent_hash, self.first['candidate_policy_sha256'],
                       self.second['candidate_policy_sha256']]
        self.args = SimpleNamespace(benchmark='remem', gpu=3, policy=self.root/'parent.json',
            ledger=self.root/'ledger.json', qualification=self.root/'qualification.json',
            output=self.root/'study')
        learn.write(self.args.policy, self.parent)
        learn.write(self.args.qualification, {'passed': True, 'source_hashes': STAMP})
        self.executions = []; self.requests = []
        self.gain = True; self.reserve_passes = True; self.invalid_round = None
        self.repeat_second = False; self.zero_parent = False
        self.pause_at = None
        owner = self

        class FakeProvider:
            def __init__(self, output):
                async def close(): pass
                self._client = SimpleNamespace(close=close)

            async def chat(self, **request):
                owner.requests.append(copy.deepcopy(request))
                payload = json.loads(request['messages'][1]['content'])
                # The real builder must only expose development cases.
                owner.assertFalse(payload['reserved_validation_and_test_access'])
                cases = payload['development_cases']
                owner.assertEqual({c['seed'] for c in cases}, set(SPLITS['development']))
                owner.assertEqual({c['split'] for c in cases}, {'development'})
                if len(owner.requests) == owner.invalid_round:
                    return {'finish_reason': 'stop', 'tool_calls': []}
                return {'finish_reason': 'tool_calls', 'tool_calls': [{
                    'name': 'propose_memory_rule_edit', 'arguments': edit(len(owner.requests) == 2 and not owner.repeat_second)}]}

        self.patches = [patch.object(study, 'HERE', self.root),
            patch.object(study.run_trial, 'source_hashes', return_value=STAMP),
            patch.object(study.run_trial, 'native_policy_hash', return_value=NATIVE),
            patch.object(study.subprocess, 'run', side_effect=self.fake_trial),
            patch.object(learn, 'provider_components', return_value=(FakeProvider, lambda *args, **kw: 5000))]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def fake_trial(self, cmd, check=False):
        flags = dict(zip(cmd[2::2], cmd[3::2]))
        phase, method, seed = flags['--phase'], flags['--method'], int(flags['--seed'])
        policy = json.loads(Path(flags['--policy']).read_text())
        ph = NATIVE if method == 'native' else policy_sha256(policy)
        out = Path(flags['--output'])
        if self.pause_at == (phase, method, seed):
            learn.write(out/'waiting-learning-budget.json', {'paused': True})
            return SimpleNamespace(returncode=75)
        self.executions.append((phase, method, seed, ph))
        # Small actual charge verifies the cumulative ledger without imposing a
        # whole-study worst-case prepayment. This fake never executes a model.
        if phase != 'test': charge(self.args.ledger, 'fake_full_trajectory', str(out))
        meta = dict(benchmark='remem', seed=seed, split=phase, method=method,
                    policy_sha256=ph, source_hashes=STAMP)
        learn.write(out/'started.json', meta)
        index = seed - SPLITS[phase][0]
        if phase == 'development':
            threshold = 2 if ph == self.parent_hash else (6 if ph == self.hashes[1] and self.gain else 1)
        elif phase == 'validation':
            threshold = 4 if ph == self.parent_hash else (6 if self.reserve_passes else 2)
        else: threshold = 3 if method == 'native' else 8
        success = index < threshold
        row = {k: v for k, v in meta.items() if k != 'source_hashes'}
        row.update(status='success' if success else 'task_failure', official_success=success)
        if self.zero_parent and phase=='development' and ph==self.parent_hash:
            row.update(status='protocol_failure',official_success=False)
        learn.write(out/'scored-record.json', row)
        audit = dict(event_id=1, public_request='Place the visible object as previously requested.',
            snapshot_scope='decision_boundary_not_archive_attribution', memory_before='pending observation',
            memory_after='pending observation', guidance_selected='uncertain public evidence',
            choice=dict(skill='execute', instruction='Move the visible object.', reason='Use public evidence.',
                        observation=dict(visible_facts='An object is visible.',
                                         progress_uncertainty='Completion is uncertain.', reference_to_preserve='')))
        actor = out/'actor'; actor.mkdir(exist_ok=True)
        (actor/'public-action-audit.jsonl').write_text(json.dumps(audit)+'\n')
        (actor/'public-receipts.jsonl').write_text(json.dumps({
            'preceding_action_event': 1, 'public_receipt': 'Executed a bounded controller segment.'})+'\n')
        if self.zero_parent and phase=='development' and ph==self.parent_hash:
            (actor/'public-action-audit.jsonl').unlink()
            (actor/'public-receipts.jsonl').unlink()
            (actor/'public-decision-inputs.jsonl').write_text(json.dumps(dict(event_id=1,
                public_request=audit['public_request'],memory_before=audit['memory_before'],
                snapshot_scope='before_decision_not_archive_attribution'))+'\n')
        return SimpleNamespace(returncode=0)

    def run_study(self): asyncio.run(study.run(self.args))

    def test_complete_full_manifests_cache_parent_and_preserve_actual_budget(self):
        self.run_study()
        self.assertEqual(len(self.executions), 36 + 24 + 96)
        self.assertEqual(len(self.requests), 2)
        # Round one's accepted candidate is reused as round two's parent.
        self.assertEqual(sum(p == 'development' and h == self.hashes[1]
            for p, m, s, h in self.executions), 12)
        test = [x for x in self.executions if x[0] == 'test']
        self.assertEqual({x[1] for x in test}, {'native', 'post'})
        self.assertEqual(sum(x[1] == 'native' for x in test), 48)
        state = study.read(self.args.output/'adaptation-state.json')
        self.assertEqual(state['phase'], 'complete')
        self.assertEqual(state['budget']['calls'], 8986 + 60 + 2)
        self.assertEqual(state['budget']['limit'], 9745)
        self.assertEqual(state['final_result']['by_benchmark']['remem']['post']['success'], 8)
        self.assertEqual(state['final_result']['claim_scope'], 'whole_method_vs_native_not_isolated_evolution')
        released = study.read(self.root/'release.json')
        self.assertEqual(released['selection']['remem']['initial_policy_sha256'], self.parent_hash)
        self.run_study()
        self.assertEqual(len(self.executions), 156)
        self.assertEqual(len(self.requests), 2)

    def test_no_gain_keeps_initial_rule_and_completes_requested_formal_trials(self):
        self.gain = False
        self.run_study()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(self.executions), 36 + 96)
        self.assertFalse(any(x[0] == 'validation' for x in self.executions))
        result = study.read(self.args.output/'study-complete.json')['result']
        self.assertEqual(result['selection_basis'], 'unchanged_parent_fallback')
        self.assertFalse(result['evolution_supported'])
        self.assertFalse(result['new_domain_rule_adopted'])
        self.assertEqual({x[3] for x in self.executions if x[0] == 'test' and x[1] == 'post'}, {self.parent_hash})
        self.assertEqual(len([x for x in self.executions if x[0] == 'test']), 96)

    def test_failed_reserve_falls_back_and_never_tunes_from_reserved_cases(self):
        self.reserve_passes = False
        self.run_study()
        self.assertEqual(len(self.executions), 60 + 96)
        self.assertEqual(len(self.requests), 2)
        state = study.read(self.args.output/'adaptation-state.json')
        self.assertEqual(state['termination_reason'], 'reserved_validation_not_passed')
        self.assertFalse(state['validation_result']['passed'])
        self.assertEqual(state['final_result']['selection_basis'], 'unchanged_parent_fallback')
        self.assertFalse(state['final_result']['evolution_supported'])
        self.assertEqual({x[3] for x in self.executions if x[0] == 'test' and x[1] == 'post'}, {self.parent_hash})
        self.run_study()
        self.assertEqual(len(self.executions), 60 + 96)

    def test_invalid_first_proposal_falls_back_without_automatic_resampling(self):
        self.invalid_round = 1
        self.run_study(); self.run_study()
        self.assertEqual(len(self.executions), 12 + 96)
        self.assertEqual(len(self.requests), 1)
        result = study.read(self.args.output/'study-complete.json')['result']
        self.assertEqual(result['selection_basis'], 'unchanged_parent_fallback')
        self.assertFalse(result['evolution_supported'])
        self.assertFalse(any(x[0] == 'validation' for x in self.executions))

    def test_invalid_second_proposal_preserves_round_one_adoption(self):
        self.invalid_round = 2
        self.run_study()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(self.executions), 24 + 24 + 96)
        state = study.read(self.args.output/'adaptation-state.json')
        self.assertEqual(state['current_policy_sha256'], self.hashes[1])
        self.assertEqual(state['phase'], 'complete')
        self.assertTrue(state['validation_used'])
        self.assertEqual(len(state['rounds']), 1)

    def test_budget_pause_is_not_no_gain_and_preserves_complete_trajectories(self):
        self.pause_at = ('development', 'pre', 2005)
        with self.assertRaisesRegex(study.StagePaused, 'learning_budget_wait'):
            self.run_study()
        self.assertEqual(len(self.executions), 5)
        self.assertFalse((self.args.output/'study-complete.json').exists())
        paused = study.read(self.args.output/'paused.json')
        self.assertFalse(paused['capability_failure'])
        self.pause_at = None; self.run_study()
        self.assertEqual(len(self.executions), 156)
        self.assertEqual(sum(x[:3] == ('development', 'pre', 2000) for x in self.executions), 1)

    def test_resume_after_formal_pause_does_not_repeat_reserved_gate_executions(self):
        self.pause_at = ('test', 'native', 2204)
        with self.assertRaises(study.StagePaused): self.run_study()
        self.assertEqual(sum(x[0] == 'validation' for x in self.executions), 24)
        self.pause_at = None; self.run_study()
        self.assertEqual(sum(x[0] == 'validation' for x in self.executions), 24)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(self.executions), 156)

    def test_source_change_and_registered_plan_change_fail_before_new_execution(self):
        self.pause_at = ('development', 'pre', 2001)
        with self.assertRaises(study.StagePaused): self.run_study()
        with patch.object(study.run_trial, 'source_hashes', return_value={'changed': True}):
            with self.assertRaisesRegex(study.StagePaused, 'engineering_qualification'):
                self.run_study()
        changed = parent_policy(); changed['guidance'] += ' '
        learn.write(self.args.policy, changed)
        with self.assertRaisesRegex(ValueError, 'immutable_artifact_changed'): self.run_study()
        self.assertEqual(len(self.executions), 1)

    def development_fixture(self):
        rows, paths = study.batch(self.args, 'development', {'pre': self.args.policy})
        return paths['pre']

    def test_exporter_refuses_heldout_or_missing_cases_before_opening_action_traces(self):
        paths = self.development_fixture()
        path = paths[2011]/'started.json'; meta = study.read(path); meta['split'] = 'test'; learn.write(path, meta)
        with patch.object(learn, 'lines') as reader:
            with self.assertRaisesRegex(ValueError, 'development_identity'):
                learn.export_manifest('remem', self.parent, paths, self.root/'export', STAMP)
            reader.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'incomplete_development'):
            learn.export_manifest('remem', self.parent, dict(list(paths.items())[:-1]), self.root/'export', STAMP)

    def test_exporter_rejects_private_fields_and_changed_official_identity(self):
        paths = self.development_fixture(); path = paths[2000]/'scored-record.json'
        row = study.read(path); row['expected_private'] = 'oracle'
        learn.write(path, row)
        with self.assertRaises(ValueError):
            learn.export_manifest('remem', self.parent, paths, self.root/'export', STAMP)
        del row['expected_private']; row['seed'] = 2011; learn.write(path, row)
        with self.assertRaisesRegex(ValueError, 'development_score_identity'):
            learn.export_manifest('remem', self.parent, paths, self.root/'export', STAMP)

    def test_cached_capability_failure_is_reused_but_technical_failure_is_not_retried(self):
        row, folder = study.one(self.args, 'development', 'pre', self.args.policy, 2011)
        self.assertEqual(row['status'], 'task_failure')
        study.one(self.args, 'development', 'post', self.args.policy, 2011)
        self.assertEqual(len(self.executions), 1)
        row['status'] = 'technical_failure'; learn.write(folder/'scored-record.json', row)
        with self.assertRaisesRegex(study.StagePaused, 'technical_case_requires_audit'):
            study.one(self.args, 'development', 'pre', self.args.policy, 2011)
        self.assertEqual(len(self.executions), 1)

    def test_partial_attempt_or_unmatched_source_never_runs_again(self):
        folder = self.args.output/'trajectories/development'/self.parent_hash/'2000'
        learn.write(folder/'started.json', {'seed': 2000})
        with self.assertRaisesRegex(study.StagePaused, 'requires_audit_no_resampling'):
            study.one(self.args, 'development', 'pre', self.args.policy, 2000)
        self.assertEqual(self.executions, [])
        row, folder = study.one(self.args, 'development', 'pre', self.args.policy, 2001)
        meta = study.read(folder/'started.json'); meta['source_hashes'] = {}; learn.write(folder/'started.json', meta)
        with self.assertRaisesRegex(study.StagePaused, 'frozen_source_changed'):
            study.one(self.args, 'development', 'pre', self.args.policy, 2001)
        self.assertEqual(len(self.executions), 1)

    def test_proposal_uncertain_charge_cannot_create_a_second_model_request(self):
        paths = self.development_fixture()
        manifest = learn.export_manifest('remem', self.parent, paths, self.root/'export', STAMP)
        out = self.root/'proposal'
        charge(self.args.ledger, 'rule_proposal', str(out.resolve()))
        with self.assertRaisesRegex(learn.ProposalPaused, 'charged_proposal_without_response'):
            asyncio.run(learn.propose(self.args.policy, manifest, self.args.ledger, out))
        self.assertEqual(self.requests, [])

    def test_proposal_rejection_and_missing_response_do_not_resample(self):
        paths = self.development_fixture()
        manifest = learn.export_manifest('remem', self.parent, paths, self.root/'export', STAMP)
        out = self.root/'proposal'; self.invalid_round = 1
        result = asyncio.run(learn.propose(self.args.policy, manifest, self.args.ledger, out))
        self.assertTrue(result['rejected'])
        result = asyncio.run(learn.propose(self.args.policy, manifest, self.args.ledger, out))
        self.assertTrue(result['rejected']); self.assertEqual(len(self.requests), 1)
        (out/'rejection.json').unlink(); (out/'response.json').unlink()
        with self.assertRaisesRegex(learn.ProposalPaused, 'prior_proposal_requires_audit'):
            asyncio.run(learn.propose(self.args.policy, manifest, self.args.ledger, out))
        self.assertEqual(len(self.requests), 1)

    def test_actual_ledger_is_not_reset_or_silently_expanded(self):
        learn.write(self.args.ledger, {'inherited_used': 8986, 'used': 9300, 'authorized_limit': 9745, 'entries': []})
        self.assertEqual(study.LedgerBudget(self.args.ledger).snapshot()['calls'], 9300)
        study.one(self.args, 'development', 'pre', self.args.policy, 2000)
        self.assertEqual(study.LedgerBudget(self.args.ledger).snapshot()['calls'], 9301)
        d = study.read(self.args.ledger); d['authorized_limit'] += 4000; learn.write(self.args.ledger, d)
        with self.assertRaisesRegex(ValueError, 'authorization_missing'):
            study.LedgerBudget(self.args.ledger).snapshot()

    def test_proposal_budget_wait_does_not_charge_until_explicit_authorization(self):
        paths = self.development_fixture()
        manifest = learn.export_manifest('remem', self.parent, paths, self.root/'export', STAMP)
        ledger = study.read(self.args.ledger); ledger['used'] = 9745
        learn.write(self.args.ledger, ledger); out = self.root/'proposal'
        with self.assertRaisesRegex(learn.ProposalPaused, 'budget_exhausted_before_proposal'):
            asyncio.run(learn.propose(self.args.policy, manifest, self.args.ledger, out))
        self.assertFalse((out/'attempt-started.json').exists())
        self.assertEqual(self.requests, [])
        self.assertEqual(study.read(self.args.ledger)['used'], 9745)
        ledger['authorized_limit'] = 10000
        ledger['additional_authorization'] = {'user_message': 'offline test authorization only', 'total_limit': 10000}
        learn.write(self.args.ledger, ledger)
        result = asyncio.run(learn.propose(self.args.policy, manifest, self.args.ledger, out))
        self.assertFalse(result['adopted'])
        self.assertEqual(study.read(self.args.ledger)['used'], 9746)
        self.assertEqual(len(self.requests), 1)

    def test_proposal_uses_same_admission_lock_as_full_trajectory(self):
        paths = self.development_fixture()
        manifest = learn.export_manifest('remem', self.parent, paths, self.root/'export', STAMP)
        actual_charge = learn.charge
        def inspect_lock(*args):
            # A second independent descriptor must not obtain the admission
            # lock while the proposal reserves its request.
            with self.args.ledger.with_suffix('.admission.lock').open('a') as other:
                with self.assertRaises(BlockingIOError):
                    learn.fcntl.flock(other, learn.fcntl.LOCK_EX | learn.fcntl.LOCK_NB)
            return actual_charge(*args)
        with patch.object(learn, 'charge', side_effect=inspect_lock):
            asyncio.run(learn.propose(self.args.policy, manifest, self.args.ledger, self.root/'proposal'))
        self.assertEqual(len(self.requests), 1)

    def test_release_rejects_changed_source_and_unvalidated_policy_file(self):
        from adaptation_protocol import AdaptationProtocol
        protocol = AdaptationProtocol(self.parent_hash, benchmarks=('remem',))
        protocol.current_policy = self.hashes[1]
        protocol.phase = 'ready_for_final_test'; protocol.validation_used = True
        protocol.selection_basis = 'validated_candidate'; protocol.evolution_supported = True
        protocol.validation_result = {'passed': True, 'effect': {'success_gain': 2}}
        selected = self.root/'selected.json'; learn.write(selected, self.first['candidate_policy'])
        study.release(self.args, protocol, self.args.policy, selected)
        original_release = (self.root/'release.json').read_bytes()
        learn.write(selected, self.second['candidate_policy'])
        with self.assertRaisesRegex(study.StagePaused, 'validated_policy_file_changed'):
            study.release(self.args, protocol, self.args.policy, selected)
        self.assertEqual(original_release, (self.root/'release.json').read_bytes())
        learn.write(selected, self.first['candidate_policy'])
        released = study.read(self.root/'release.json'); released['source_hashes'] = {'different': True}
        learn.write(self.root/'release.json', released)
        with self.assertRaisesRegex(study.StagePaused, 'release_source_changed'):
            study.release(self.args, protocol, self.args.policy, selected)

    def test_fallback_release_never_allows_rejected_candidate_policy(self):
        from adaptation_protocol import AdaptationProtocol
        protocol = AdaptationProtocol(self.parent_hash, benchmarks=('remem',))
        protocol.stop_without_improvement('no_development_candidate_adopted')
        protocol.select_parent_fallback()
        selected = self.root/'selected.json'; learn.write(selected, self.first['candidate_policy'])
        with self.assertRaisesRegex(study.StagePaused, 'validated_policy_file_changed'):
            study.release(self.args, protocol, self.args.policy, selected)
        self.assertFalse((self.root/'release.json').exists())
        study.release(self.args, protocol, self.args.policy, self.args.policy)
        released = study.read(self.root/'release.json')
        self.assertEqual(released['selection']['remem']['basis'], 'unchanged_parent_fallback')
        self.assertEqual(released['selection']['remem']['initial_policy_sha256'], self.parent_hash)
        self.assertFalse(released['selection']['remem']['evolution_supported'])
        self.assertIsNone(released['validation']['remem'])

    def test_repeated_rejected_candidate_freezes_without_pause_or_reexecution(self):
        self.gain=False; self.repeat_second=True
        self.run_study()
        self.assertEqual(len(self.requests),2)
        self.assertEqual(sum(x[0]=='development' for x in self.executions),24)
        self.assertEqual(sum(x[0]=='test' for x in self.executions),96)
        self.assertTrue((self.args.output/'round-2/duplicate-candidate.json').exists())
        self.assertFalse((self.args.output/'paused.json').exists())
        self.assertEqual(study.read(self.args.output/'study-complete.json')['result']['selection_basis'],
                         'unchanged_parent_fallback')
        self.run_study()
        self.assertEqual(len(self.requests),2);self.assertEqual(len(self.executions),120)

    def test_zero_valid_action_failures_remain_in_real_proposer_input(self):
        self.zero_parent=True
        self.run_study()
        cases=json.loads(self.requests[0]['messages'][1]['content'])['development_cases']
        self.assertEqual(len(cases),12)
        for case in cases:
            self.assertEqual(case['events'],[])
            self.assertTrue(case['zero_recorded_valid_actions'])
            self.assertEqual(case['terminal_status'],'protocol_failure')
            self.assertFalse(case['official_success'])
            self.assertEqual(case['public_initial_request_availability'],'observed')
            self.assertEqual(case['public_decision_inputs'][0]['memory_before']['text'],'pending observation')
            self.assertEqual(case['memory_evidence'],[])
        self.assertEqual(sum(x[0]=='test' for x in self.executions),96)

    def test_zero_action_missing_inputs_are_unknown_not_inferred(self):
        self.zero_parent=True
        paths=self.development_fixture()
        for path in paths.values():
            (path/'actor/public-decision-inputs.jsonl').unlink()
            record=study.read(path/'scored-record.json');record['status']='capacity_failure'
            learn.write(path/'scored-record.json',record)
        manifest=learn.export_manifest('remem',self.parent,paths,self.root/'export',STAMP)
        from visual_rule_proposal import load_development_evidence
        cases=load_development_evidence(manifest,self.parent_hash)
        self.assertEqual(len(cases),12)
        for case in cases:
            self.assertEqual(case['events'],[])
            self.assertNotIn('public_initial_request',case)
            self.assertEqual(case['public_initial_request_availability'],'unknown')
            self.assertEqual(case['pre_decision_memory_availability'],'unknown')
            self.assertEqual(case['terminal_status'],'capacity_failure')

    def test_second_proposal_receives_actual_accepted_first_round_feedback(self):
        self.run_study()
        first=json.loads(self.requests[0]['messages'][1]['content'])
        second=json.loads(self.requests[1]['messages'][1]['content'])
        self.assertIsNone(first['previous_development_feedback'])
        feedback=second['previous_development_feedback']
        self.assertEqual(second['proposal_round'],2)
        self.assertTrue(feedback['accepted'])
        self.assertEqual(feedback['paired_effect']['success_gain'],4)
        self.assertEqual(feedback['local_edit'],{k:edit()[k] for k in ('operator','anchor','replacement')})
        self.assertEqual(feedback['parent_policy_sha256'],self.parent_hash)
        self.assertEqual(feedback['candidate_policy_sha256'],self.hashes[1])
        self.assertEqual({r['seed'] for r in feedback['paired_outcomes']},set(SPLITS['development']))
        self.assertEqual(sum(r['success_change'] for r in feedback['paired_outcomes']),4)
        self.assertTrue(feedback['all_development_pairs_retained'])
        self.assertFalse(feedback['paired_outcomes_truncated'])
        self.assertNotIn('source_hashes',feedback)
        self.assertNotIn('parent_policy',feedback)

    def test_rejected_edit_and_negative_outcomes_are_in_second_real_request(self):
        self.gain=False
        self.run_study()
        second=json.loads(self.requests[1]['messages'][1]['content'])
        feedback=second['previous_development_feedback']
        self.assertFalse(feedback['accepted'])
        self.assertEqual(second['parent_policy_sha256'],self.parent_hash)
        self.assertEqual(feedback['paired_effect']['success_gain'],-1)
        self.assertEqual(feedback['paired_outcomes'][1]['parent_status'],'success')
        self.assertEqual(feedback['paired_outcomes'][1]['candidate_status'],'task_failure')
        self.assertEqual(len(feedback['paired_outcomes']),12)
        self.assertEqual(feedback['local_edit']['replacement'],edit()['replacement'])

    def test_feedback_rejects_contamination_tampering_missing_pairs_and_stale_round(self):
        self.gain=False;self.run_study()
        value=study.read(self.args.output/'round-1/development-feedback.json')
        manifest=self.args.output/'round-2/evidence/manifest.json'
        mutations=[]
        for field,new in (('split','validation'),('benchmark','rmbench'),('round',2),
                          ('source_hashes',{'changed':'x'}),('candidate_policy_sha256','0'*64)):
            bad=copy.deepcopy(value);bad[field]=new;mutations.append(bad)
        for field,new in (('split','test'),('seed',2200),('policy_sha256','a'*64),
                          ('expected_private','do something'),('method','native')):
            bad=copy.deepcopy(value);bad['rows'][-1][field]=new;mutations.append(bad)
        bad=copy.deepcopy(value);bad['rows'].pop();mutations.append(bad)
        bad=copy.deepcopy(value);bad['selection']['accepted']=True;mutations.append(bad)
        bad=copy.deepcopy(value);bad['proposal']['replacement']='Changed unexecuted edit';mutations.append(bad)
        for bad in mutations:
            with self.subTest(value=bad),self.assertRaises(ValueError):
                build_proposal_request(self.parent,manifest,self.parent_hash,token_counter=lambda *x:5000,
                    previous_development_feedback=bad,expected_source_hashes=STAMP,proposal_round=2)
        with self.assertRaisesRegex(ValueError,'feedback_required'):
            build_proposal_request(self.parent,manifest,self.parent_hash,proposal_round=2)
        with self.assertRaisesRegex(ValueError,'round_mismatch'):
            build_proposal_request(self.parent,manifest,self.parent_hash,
                previous_development_feedback=value,expected_source_hashes=STAMP,proposal_round=1)

    def test_feedback_collector_checks_all_sources_before_any_scores_and_preserves_raw_files(self):
        self.run_study()
        raw=self.args.output/'round-1/development-feedback.json'
        stored=raw.read_bytes()
        paths={m:{s:self.args.output/'trajectories/development'/h/str(s) for s in SPLITS['development']}
               for m,h in (('pre',self.parent_hash),('post',self.hashes[1]))}
        last=paths['post'][2011]/'started.json';meta=study.read(last)
        meta['split']='validation';learn.write(last,meta)
        seen=[];read_text=Path.read_text
        def observe(path,*args,**kwargs):
            seen.append(path.name);return read_text(path,*args,**kwargs)
        with patch.object(Path,'read_text',observe),self.assertRaisesRegex(ValueError,'identity_mismatch'):
            learn.export_previous_development_feedback('remem',1,self.parent,self.first,paths,
                study.read(self.args.output/'round-1/selection.json'),self.hashes[1],
                self.root/'bad-feedback.json',STAMP)
        self.assertNotIn('scored-record.json',seen)
        self.assertFalse((self.root/'bad-feedback.json').exists())
        self.assertEqual(raw.read_bytes(),stored)

    def test_previous_feedback_compression_is_explicit_and_never_drops_failed_pairs(self):
        self.gain=False;self.run_study()
        value=study.read(self.args.output/'round-1/development-feedback.json')
        value['proposal']['rationale']='reason '*100
        original=copy.deepcopy(value)
        manifest=self.args.output/'round-2/evidence/manifest.json'
        def counter(messages,tools):
            data=json.loads(messages[1]['content'])
            return 5000 if data['memory_excerpt_character_cap']<=128 else 9001
        request=build_proposal_request(self.parent,manifest,self.parent_hash,token_counter=counter,
            previous_development_feedback=value,expected_source_hashes=STAMP,proposal_round=2)
        feedback=json.loads(request['messages'][1]['content'])['previous_development_feedback']
        self.assertTrue(feedback['proposal_rationale']['truncated'])
        self.assertEqual(len(feedback['proposal_rationale']['text']),128)
        self.assertEqual(feedback['local_edit']['replacement'],edit()['replacement'])
        self.assertEqual(len(feedback['paired_outcomes']),12)
        self.assertEqual(value,original)
        with self.assertRaisesRegex(ValueError,'proposal_input_budget'):
            build_proposal_request(self.parent,manifest,self.parent_hash,token_counter=lambda *x:9001,
                previous_development_feedback=value,expected_source_hashes=STAMP,proposal_round=2)


if __name__ == '__main__': unittest.main()
