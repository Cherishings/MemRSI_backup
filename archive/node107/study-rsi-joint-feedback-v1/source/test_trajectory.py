import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from trajectory_evolution import apply_edit, select, replay_case, run
from stream_design import SEED_PROCEDURES


class Edits(unittest.TestCase):
    def test_local_edit_preserves_other_operator(self):
        parent = copy.deepcopy(SEED_PROCEDURES)
        p = dict(target='guidance', anchor='Empty selection is allowed.',
                 replacement='Empty selection is allowed when the evidence is irrelevant.', rationale='generic')
        value, policy = apply_edit(parent, p)
        self.assertEqual(value['update'], parent['update'])
        self.assertTrue(value['guidance'].startswith(parent['guidance'].split(p['anchor'])[0]))
        self.assertEqual(parent, SEED_PROCEDURES)
        with self.assertRaises(ValueError):apply_edit(parent, dict(p, anchor=parent['guidance']))
        with self.assertRaises(ValueError):apply_edit(parent, dict(p, anchor='nonexistent fragment'))

    def test_optional_anchor_can_append_without_invalid_required_empty_field(self):
        value, _ = apply_edit(SEED_PROCEDURES, dict(target='guidance', replacement='Distinguish conflicting evidence.', rationale='generic'))
        self.assertTrue(value['guidance'].startswith(SEED_PROCEDURES['guidance']))

    def make(self, a, b, sa='completed', sb='completed'):
        return [dict(case='case', repeat=i, policy=k, status=status, correct=c, answered=c,
                     planned=7, all_attempt_calls=10)
                for i in range(2) for k, c, status in [('parent', a, sa), ('candidate', b, sb)]]

    def test_select_scores_whole_checkpoint_sequence(self):
        self.assertFalse(select(self.make(7, 1, sb='decision_failure'), 2)['accepted'])
        self.assertTrue(select(self.make(5, 6, 'decision_failure', 'decision_failure'), 2)['accepted'])
        self.assertFalse(select(self.make(7, 7), 2)['accepted'])
        self.assertFalse(select(self.make(0, 7, 'technical_failure', 'completed'), 2)['accepted'])
        self.assertFalse(select(self.make(0, 7, 'decision_failure', 'completed'), 3)['accepted'])
        # A known archive/protocol failure is recorded, not silently excluded as transport.
        self.assertTrue(select(self.make(0, 7, 'agent_failure', 'completed'), 2)['accepted'])


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_retry_for_archive_failure(self):
        async def fail(*a):return dict(status='agent_failure', error_code='native_session_archival_failed', correct=0, answered=0, planned=7)
        with tempfile.TemporaryDirectory() as d, patch('trajectory_evolution.evaluate', fail):
            r = await replay_case({}, Path(d)/'r', {}, {}, lambda: None)
            self.assertEqual(r['attempts'], 1)

    async def test_transport_retry_is_bounded(self):
        async def fail(*a):return dict(status='technical_failure', correct=0, answered=0, planned=7)
        with tempfile.TemporaryDirectory() as d, patch('trajectory_evolution.evaluate', fail):
            r = await replay_case({}, Path(d)/'r', {}, {}, lambda: None)
            self.assertEqual(r['attempts'], 3)

    async def test_optimizer_budget_is_not_a_model_failure_or_retry(self):
        async def fail(*a):return dict(status='learning_budget_exhausted')
        with tempfile.TemporaryDirectory() as d, patch('trajectory_evolution.evaluate', fail):
            with self.assertRaisesRegex(RuntimeError, 'optimizer_call_budget'):
                await replay_case({}, Path(d)/'r', {}, {}, lambda: None)

    async def test_rebuild_archives_and_stop_on_first_wrong_checkpoint(self):
        from trajectory_replay import evaluate
        visits = []
        class Agent:
            def __init__(self, *a):pass
            async def replay_observe(self, text, action):visits.append(('prefix', text))
            async def observe_only(self, text):visits.append(('feedback', text))
            async def rollover(self):visits.append(('archive', None))
            async def turn(self, text, decision):
                visits.append(('decision', text));return {'skill': 'wrong'}
            async def close(self):pass
        f = {'source': 'development', 'targets': [3, 5], 'archives': [2, 4],
             'events': [{'id': i, 'text': str(i)} for i in range(1, 6)],
             'decisions': {i: {'skill': 'right', 'expected_private': 'right'} for i in (1, 3, 5)}}
        with tempfile.TemporaryDirectory() as d, patch('twenty_agent.TwentyAgent', Agent):
            r = await evaluate(f, Path(d)/'r', {}, {})
        self.assertEqual(r['planned'], 2);self.assertEqual(r['answered'], 1)
        self.assertEqual(r['correct'], 0);self.assertEqual(r['status'], 'decision_failure')
        self.assertIn(('archive', None), visits);self.assertNotIn(('decision', '5'), visits)

    async def test_archive_error_has_explicit_classification(self):
        from trajectory_replay import evaluate
        class Agent:
            def __init__(self, *a):pass
            async def observe_only(self, *a):pass
            async def rollover(self):raise RuntimeError('native_session_archival_failed')
            async def close(self):pass
        f = {'source': 'development', 'targets': [2], 'archives': [1],
             'events': [{'id': 1, 'text': 'public'}], 'decisions': {}}
        with tempfile.TemporaryDirectory() as d, patch('twenty_agent.TwentyAgent', Agent):
            r = await evaluate(f, Path(d)/'r', {}, {})
        self.assertEqual(r['status'], 'agent_failure')
        self.assertEqual(r['error_code'], 'native_session_archival_failed')
        self.assertEqual(r['failure_phase'], 'archive')


class LearningTest(unittest.IsolatedAsyncioTestCase):
    async def test_promoted_rule_changes_next_physical_batch(self):
        import trajectory_evolution as m
        class E:
            def __init__(self):self.parents=[]
            def state(self, *a, **k):pass
            def wait_gateway(self):pass
            def batch(self, rows, policies, out):
                self.parents.append(json.loads(Path(policies['memrsi']).read_text()))
                return []
        async def propose(path, system, data, schema, wait):
            if str(path).endswith('critic'):return dict(generic=True, no_task_answers=True, preserves_user_authority=True)
            return dict(target='guidance', replacement=' Check provenance.' if len(e.parents)==1 else ' Check scope.', rationale='generic')
        async def measure(*args):
            return [dict(case='case',repeat=i,policy=k,status='decision_failure' if k=='parent' else 'completed',
                         correct=5 if k=='parent' else 7,planned=7,answered=6 if k=='parent' else 7,all_attempt_calls=10)
                    for i in range(2) for k in ('parent','candidate')]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'prior/learning').mkdir(parents=True)
            (root/'prior/learning/learning-call-ledger.json').write_text(json.dumps(dict(calls=3769,limit=6000)))
            e=E()
            with patch.object(m,'choose_sources',return_value=([{'id':'case'}],[])),patch.object(m,'proposal_data',return_value={}),patch.object(m,'cached_structured',propose),patch.object(m,'paired',measure):
                r=await run(root/'new',e,{},root/'old',root/'prior')
            self.assertEqual(r['promotions'],2);self.assertNotEqual(e.parents[0],e.parents[1])
            self.assertEqual(json.loads((root/'new/learning-call-ledger.json').read_text())['calls'],3769)


if __name__ == '__main__':unittest.main()
