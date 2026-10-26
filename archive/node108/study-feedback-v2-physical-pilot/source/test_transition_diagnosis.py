import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from replay import dump
from transition_diagnosis import (pick_row,public_text,evidence_units,pack_units,validate_diagnosis,prior_contrasts)
from diagnosed_learning import reuse_parent_if_identical

class EvidenceTests(unittest.TestCase):
    def test_real_failure_precedes_corrected_source_control(self):
        rows=[dict(repeat=0,status='source_error_corrected',decisions=[{'correct':True}]),
              dict(repeat=1,status='decision_failure',decisions=[{'correct':False}])]
        self.assertEqual(pick_row(rows)['repeat'],1)

    def test_feedback_is_retained_scene_removed(self):
        self.assertEqual(public_text('Execution feedback: job complete. Current scene {...}'),'Execution feedback: job complete.')

    def test_complete_transitions_include_feedback_no_future(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'x-r0-parent/attempt-01'
            for e in (3,5):
                a=d/f'rollover-{e}';dump(a/'audit.json',{'last_received_event':e,'success':True})
                (a/'memory-before.md').write_text('pending special obligation')
                (a/'memory-after.md').write_text('task cancelled')
                dump(a/'messages-before.json',[{'role':'user','content':'Execution feedback: unrelated job finished. Current scene secret'}])
            (d/'guidance-events.jsonl').write_text(json.dumps({'current_request':'Event 4: Continue.','long_memory':'pending','generated':{'quotes':[]}})+'\n')
            row=dict(case='x',repeat=0,attempts=1,decisions=[{'event':4,'correct':False,'skill':'finish'}])
            f={'targets':[4],'decisions':{4:{'expected_private':'continue'}}}
            units=evidence_units(f,row,root)
            self.assertEqual([x['event'] for x in units],[3,4])
            self.assertEqual(units[0]['documents']['archive-3-before'],'pending special obligation')
            self.assertIn('Execution feedback',units[0]['documents']['archive-3-received'])
            self.assertNotIn('secret',units[0]['documents']['archive-3-received'])

    def test_diagnostic_quotes_must_exist(self):
        value={'target':'update','witness_a':'before','quote_a':'old obligation','witness_b':'after','quote_b':'done','finding':'hypothesis'}
        docs={'before':'keep old obligation','after':'all done'}
        self.assertEqual(validate_diagnosis(value,docs),value)
        with self.assertRaises(ValueError):validate_diagnosis(dict(value,quote_b='fabricated'),docs)
        with self.assertRaises(ValueError):validate_diagnosis(dict(value,target='invented'),docs)

    def test_packing_never_clips_or_drops_a_transition(self):
        units=[dict(kind='archive',event=i,documents={str(i):'full evidence '*2000}) for i in range(4)]
        batches=pack_units(units,{'case':'test'})
        reconstructed={k:v for batch in batches for k,v in batch['documents'].items()}
        self.assertEqual(reconstructed,{k:v for u in units for k,v in u['documents'].items()})
        with self.assertRaises(RuntimeError):pack_units([dict(documents={'huge':'text '*20000})],{})

    def test_reuse_exact_policy_only_and_never_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'old';root=Path(tmp)/'new';root.mkdir();dump(source/'parent-policy.json',{'id':1})
            self.assertFalse(reuse_parent_if_identical(source,root,{'id':2}))
            with self.assertRaises(RuntimeError):reuse_parent_if_identical(source,root,{'id':1})
            rows=[]
            for i in range(8):
                r=dict(case=str(i),repeat=0,status='completed',correct=1,planned=1,attempts=1);rows.append(r)
                dump(source/'parent-replays'/f'{i}-r0-parent/result.json',r)
            dump(source/'parent-rows.json',rows)
            self.assertTrue(reuse_parent_if_identical(source,root,{'id':1}))
            self.assertTrue((root/'parent-replays').is_symlink())
            self.assertEqual((root/'parent-replays').resolve(),(source/'parent-replays').resolve())

    def test_prior_contrast_retains_regression_and_gain(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);rows=[]
            for case,values in [('bad',(3,0)),('good',(1,4))]:
                for arm,c in zip(('parent','candidate'),values):rows.append(dict(case=case,repeat=0,policy=arm,correct=c,status='decision_failure'))
            dump(p/'paired-rows.json',rows);dump(p/'selection.json',{'effect':{'accepted':False}})
            result=prior_contrasts(p)
            self.assertEqual([x['correct_delta'] for x in result['all_pair_differences']],[-3,3])

if __name__=='__main__':unittest.main()

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_actor_only_diagnosis_does_not_rewrite_memory_or_reset_budget(self):
        import diagnosed_learning as m
        class Control:
            def state(self,*a,**kw):pass
            def wait_gateway(self):pass
        f=dict(id='x',sha256='abc')
        async def replay(*a):return dict(status='completed',correct=1,answered=1,planned=1,attempts=1,decisions=[],all_attempt_calls=10)
        async def data(*a):return dict(transition_diagnoses=[dict(diagnoses=[dict(target='actor')])])
        async def forbidden(*a):raise AssertionError('no supported memory defect, must not request blind patch')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dump(root/'old/learning/learning-call-ledger.json',dict(calls=7867,limit=9745))
            with patch.object(m,'source_sets',return_value=([[f],[f]],[f])),patch.object(m,'replay_case',replay),patch.object(m,'diagnosed_packet',data),patch.object(m,'safe_structured',forbidden):
                result=await m.run(root/'new',Control(),{},'/unused',root/'old')
                again=await m.run(root/'new',Control(),{},'/unused',root/'old')
            self.assertEqual(result,again);self.assertEqual(result['promotions'],0)
            self.assertEqual(len(result['credits']),2)
            self.assertEqual(json.loads((root/'new/learning-call-ledger.json').read_text())['calls'],7867)
