import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bounded_learning as m
from stream_design import SEED_PROCEDURES, compile_procedures
from trajectory_evolution import apply_edit
from replay import dump


class BoundedRegression(unittest.TestCase):
    def test_runtime_is_original_store_for_both_arms(self):
        import twenty_agent
        source = Path(twenty_agent.__file__).read_text()
        self.assertNotIn('DeltaStore', source)
        self.assertNotIn('delta_memory', source)
        self.assertIn('self.store = BoundedStore(', source)

    def test_learning_cannot_replace_store_or_other_operator(self):
        change = dict(target='update', anchor='Keep historical details concise.',
                      replacement='Keep historical details concise; retain the latest authoritative revision.', rationale='generic')
        updated, policy = apply_edit(SEED_PROCEDURES, change)
        self.assertEqual(updated['guidance'], SEED_PROCEDURES['guidance'])
        self.assertIn('remaining_components', updated['update'])
        self.assertIn('resume_context', updated['update'])
        self.assertEqual(json.loads(policy['update'])['kind'], 'procedure_update_v2')

    def rows(self, a, b):
        return [dict(case='x', repeat=i, policy=k, correct=n, answered=n,
                     planned=7, status='decision_failure', all_attempt_calls=10)
                for i in range(2) for k,n in [('parent',a),('candidate',b)]]

    def test_validation_is_not_perfect_success_requirement(self):
        self.assertTrue(m.validation_gate(self.rows(4,5),2)['passed'])
        self.assertFalse(m.validation_gate(self.rows(5,4),2)['passed'])
        self.assertFalse(m.validation_gate(self.rows(4,5),3)['passed'])
        r=self.rows(4,5);r[0]['status']='technical_failure'
        self.assertFalse(m.validation_gate(r,2)['passed'])

    def test_actual_archive_omission_visible_to_optimizer(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dest=root/'case-r0-parent/attempt-01';a=dest/'rollover-1'
            dump(a/'audit.json',dict(success=True,last_received_event=3))
            (a/'memory-before.md').write_text('pending request; original priority')
            (a/'memory-after.md').write_text('pending request; original priority')
            dump(a/'messages-before.json',[dict(role='user',content='Event 3: Priority has changed; latest instruction applies.')])
            (dest/'guidance-events.jsonl').write_text(json.dumps(dict(current_request='Event 4: Continue.',
                long_memory='pending request; original priority',generated={'quotes':[]}))+'\n')
            f=dict(id='case',targets=[4],events=[dict(id=3,text='Event 3: Priority has changed; latest instruction applies.')],
                   decisions={4:{'expected_private':'correct'}})
            row=dict(case='case',repeat=0,attempts=1,status='decision_failure',correct=0,planned=1,
                     decisions=[dict(event=4,skill='wrong',correct=False)])
            data=m.packet(SEED_PROCEDURES,[f],[row],root,[])
            e=data['actual_parent_evidence'][0]
            self.assertIn('Priority has changed',e['public_instructions'][0])
            self.assertIn('original priority',e['archives'][0]['after'])
            self.assertEqual(e['first_wrong_decision']['expected_private'],'correct')


class BudgetAndResume(unittest.IsolatedAsyncioTestCase):
    async def test_no_gain_keeps_fixed_seed_and_budget_no_fake_rsi(self):
        class Control:
            def state(self,*a,**k):pass
            def wait_gateway(self):pass
        f=dict(id='case',sha256='abc')
        async def replay(*a):
            return dict(status='completed',correct=1,answered=1,planned=1,attempts=1,decisions=[],all_attempt_calls=10)
        async def proposal(path,*a):
            if str(path).endswith('critic'):
                return dict(generic=True,no_task_answers=True,preserves_user_authority=True)
            return dict(target='guidance',replacement=' Preserve evidence provenance.',rationale='generic')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dump(root/'prior/learning/learning-call-ledger.json',dict(calls=6463,limit=9745))
            with patch.object(m,'source_sets',return_value=([[f],[f]],[f])), \
                 patch.object(m,'replay_case',replay),patch.object(m,'packet',return_value={}), \
                 patch.object(m,'cached_structured',proposal):
                r=await m.run(root/'new',Control(),{},'/unused',root/'prior')
                again=await m.run(root/'new',Control(),{},'/unused',root/'prior')
            self.assertEqual(r,again);self.assertEqual(r['promotions'],0)
            self.assertEqual(r['status'],'no_qualified_update')
            self.assertFalse((root/'new/candidate-policy.json').exists())
            self.assertEqual(json.loads((root/'new/selected-policy.json').read_text()),compile_procedures(SEED_PROCEDURES))
            self.assertEqual(json.loads((root/'new/learning-call-ledger.json').read_text()),dict(calls=6463,limit=9745))


if __name__=='__main__': unittest.main()
