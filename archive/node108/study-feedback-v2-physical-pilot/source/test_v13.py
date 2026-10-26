"""Offline tests: routing, sealed splits, promotion, process orchestration, no model calls."""
import asyncio
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from start_v13 import gpu_ids
from feedback_protocol import schedule,histories,old_histories,DEVELOPMENT_HISTORIES,plan
from learning_v13 import physical_improves,physical_rows
from memory_policy import BASE,archive_request,screen
from memory_ops import MemoryOps
from test_guidance_format import FakeProvider,response
from experiment_v13 import Experiment

class ProtocolTests(unittest.TestCase):
    def test_any_three_cards_and_no_duplicate(self):
        for gs in ((0,6,7),(1,3,5),(2,4,7)):
            self.assertEqual(gpu_ids(gs),gs)
            rows=schedule(gs);self.assertEqual(len(rows),120)
            self.assertEqual({r['gpu'] for r in rows},set(gs))
            pairs={}
            for r in rows:pairs.setdefault((r['condition'],r['repeat']),[]).append(r)
            for pair in pairs.values():
                self.assertEqual({r['arm'] for r in pair},{'native','fixed','evolved'})
                self.assertEqual(len({(r['history'],r['gpu'],r['init']) for r in pair}),1)
        for gs in ((0,0,1),(0,1),(0,1,8),(-1,1,2)):
            with self.assertRaises(ValueError):gpu_ids(gs)
    def test_new_test_split_does_not_reuse_inspected_histories(self):
        self.assertTrue(set(histories()).isdisjoint(set(old_histories())|set(DEVELOPMENT_HISTORIES)))
        self.assertEqual(len(histories()),10)
        for h in DEVELOPMENT_HISTORIES+tuple(histories()):
            p=plan(h);self.assertEqual(len(p['sessions']),20)
            self.assertEqual(len([s for s in p['sessions'] if s['kind']=='recovery']),5)
    def test_native_archive_is_not_given_memrsi_policy(self):
        kwargs={'messages':[{'role':'system','content':'original'}],
            'tools':[{'function':{'name':'save_memory'}}]}
        empty={'schema':1,'guidance':'','update':''}
        self.assertIs(archive_request(kwargs,empty),kwargs)
        changed=archive_request(kwargs,BASE)
        self.assertNotEqual(changed,kwargs);self.assertEqual(kwargs['messages'][0]['content'],'original')
        screen(BASE)

class FullGateTests(unittest.TestCase):
    def setUp(self):
        self.parent=[{'trial_id':str(i),'status':'decision_failure','correct_checkpoints':i,
            'sessions_completed':10+i} for i in range(4)]
        self.better=copy.deepcopy(self.parent)
        self.better[0].update(status='success',correct_checkpoints=7,sessions_completed=20)
    def test_gate_requires_real_whole_episode_gain(self):
        self.assertTrue(physical_improves(self.parent,self.better))
        self.assertFalse(physical_improves(self.parent,self.parent))
        b=copy.deepcopy(self.better);b[0]['status']='decision_failure'
        self.assertFalse(physical_improves(self.parent,b))
    def test_cannot_hide_regression_or_technical_failure(self):
        for key,val in [('correct_checkpoints',0),('sessions_completed',0),('status','infrastructure_failure')]:
            b=copy.deepcopy(self.better);b[3][key]=val
            self.assertFalse(physical_improves(self.parent,b))
        self.assertFalse(physical_improves(self.parent,self.better[:-1]))
    def test_previous_success_must_remain_success(self):
        a=copy.deepcopy(self.parent);a[1].update(status='success',correct_checkpoints=7,sessions_completed=20)
        self.assertFalse(physical_improves(a,self.better))

class GuidanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_instruction_requires_instance_and_binding_but_no_answer_injection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'memory').mkdir();(root/'memory/MEMORY.md').write_text('old order completed')
            provider=FakeProvider([response({'guidance':'Task reference: new order. Suggested skill: reported choice.', 'uncertainty':''})])
            ops=MemoryOps(provider,root,root,BASE,'public capabilities')
            guide=await ops.guide([], 'new order with similar wording')
            system=provider.requests[0]['messages'][0]['content']
            self.assertIn('old completion is not completion of a new request',system)
            self.assertIn('declared scope and binding',system)
            self.assertIn('actor makes its own final choice',guide)
            self.assertNotIn('expected_private',json.dumps(provider.requests))
            self.assertEqual((root/'memory/MEMORY.md').read_text(),'old order completed')

class OrchestrationTests(unittest.TestCase):
    def test_each_trial_exactly_once_on_selected_gpu_and_policy(self):
        with tempfile.TemporaryDirectory() as d:
            e=Experiment(Path(d)/'run',(1,3,5),'orders','budget',threading.Event())
            rows=physical_rows(e.gpus);seen=[]
            def fake(row,policy,dest):
                seen.append((row['trial_id'],row['gpu'],policy))
                return dict(row,status='success',correct_checkpoints=7,sessions_completed=20)
            e.episode=fake
            result=e.batch(rows,{'memrsi':'policy'},Path(d)/'batch',True)
            self.assertEqual(len(result),4);self.assertEqual(len({x[0] for x in seen}),4)
            self.assertEqual({x[1] for x in seen},{1,3,5})
            self.assertTrue(all(x[2]=='policy' for x in seen))
    def test_technical_hold_preserves_rows_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as d:
            e=Experiment(Path(d)/'run',(0,6,7),'orders','budget',threading.Event())
            rows=[dict(trial_id=str(i),gpu=0,arm='memrsi') for i in range(3)];seen=[]
            def fake(row,policy,dest):
                seen.append(row['trial_id']);return dict(row,status='infrastructure_failure')
            e.episode=fake
            with self.assertRaisesRegex(RuntimeError,'technical_hold'):
                e.batch(rows,{'memrsi':'policy'},Path(d)/'batch',True)
            self.assertEqual(seen,['0'])
            self.assertEqual(len(json.loads((Path(d)/'batch/rows.json').read_text())),1)

if __name__=='__main__':unittest.main()

class LearningIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,full_gain=True):
        import learning_v13 as module
        from unittest.mock import AsyncMock
        fixtures=[{'source':'development','id':'dev','original_correct':False}]
        validation=[{'source':'validation','id':'val'}]
        candidate=dict(BASE,guidance=BASE['guidance']+' Preserve uncertainty explicitly.')
        async def proposal(*args):
            if str(args[0]).endswith('critic'):return dict(generic=True,no_task_answers=True,preserves_user_authority=True)
            return candidate
        async def windows(fs,out,policy):
            n=1 if policy==BASE else 2
            return dict(correct=n,planned=2,invalid=0,cost_complete=True,per_case={'x':n},tokens=100,rows=[])
        class FakeExperiment:
            gpus=(0,6,7);stop=threading.Event()
            def __init__(self):self.batches=[]
            def state(self,*a,**k):pass
            def batch(self,rows,policies,output,strict):
                self.batches.append(str(output));is_new='full-candidate' in str(output)
                return [dict(r,status='success' if full_gain and is_new and i==0 else 'decision_failure',
                    correct_checkpoints=7 if full_gain and is_new and i==0 else 0,
                    sessions_completed=20 if full_gain and is_new and i==0 else 10) for i,r in enumerate(rows)]
        fake=FakeExperiment()
        with tempfile.TemporaryDirectory() as d:
            with patch.object(module,'prepare',return_value=(fixtures,validation)),\
                 patch.object(module,'structured',side_effect=proposal),\
                 patch.object(module,'batch',side_effect=windows),\
                 patch.object(module,'evidence',return_value=[{'observed_failure':'task_identity'}]):
                report=await module.run(Path(d)/'learning',fake)
            exists=(Path(d)/'learning/accepted-policy.json').exists()
        return report,fake,exists
    async def test_full_gate_runs_before_accepting_candidate(self):
        report,fake,exists=await self.exercise()
        self.assertEqual(report['status'],'accepted');self.assertTrue(exists)
        self.assertEqual(len(fake.batches),2)
        self.assertIn('full-parent',fake.batches[0]);self.assertIn('full-candidate',fake.batches[1])
    async def test_window_gain_alone_cannot_release_evolved_policy(self):
        report,fake,exists=await self.exercise(False)
        self.assertEqual(report['status'],'no_accepted_improvement');self.assertFalse(exists)
        self.assertEqual(len(fake.batches),3) # parent once, two bounded candidates
        self.assertEqual(len(report['attempts']),2)
