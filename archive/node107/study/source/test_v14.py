import copy,json,tempfile,threading,unittest,asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from memory_design import SEED,MANDATORY,validate_design,policy,update_instruction
from memory_policy import BASE,EMPTY,archive_request
from memory_ops import MemoryOps,checked_selection,fragments
from learning_v14 import physical_improves,physical_rows,nonregression
from feedback_protocol import histories,old_histories,v13_histories,DEVELOPMENT_HISTORIES,plan,schedule
from start_v14 import gpu_ids
from experiment_v13 import Experiment

def response(ids):
    return SimpleNamespace(finish_reason='tool_calls',tool_calls=[SimpleNamespace(name='select_memory_evidence',arguments={'ids':ids})])
class FakeProvider:
    def __init__(self,responses):self.responses=list(responses);self.requests=[];self.logs=[];self.format_repairs=0
    async def chat(self,**kw):self.requests.append(kw);return self.responses.pop(0)
    def _append(self,*args):self.logs.append(args)

class DesignTests(unittest.TestCase):
    def test_required_identity_and_no_unbounded_fields(self):
        self.assertEqual(validate_design(SEED),SEED)
        for field in MANDATORY:
            d=copy.deepcopy(SEED);d['fields'].remove(field)
            with self.assertRaises(ValueError):validate_design(d)
        d=copy.deepcopy(SEED);d['fields'].append('private_answer')
        with self.assertRaises(ValueError):validate_design(d)
    def test_compiler_and_native_unchanged(self):
        kw={'messages':[{'role':'system','content':'original'}],'tools':[{'function':{'name':'save_memory'}}]}
        self.assertIs(archive_request(kw,EMPTY),kw)
        result=archive_request(kw,BASE)
        self.assertIn('distinct request INSTANCE',result['messages'][0]['content'])
        self.assertEqual(kw['messages'][0]['content'],'original')
        self.assertEqual(policy(SEED),BASE)
        pack=copy.deepcopy(kw);pack['tools'][0]['function']['name']='pack_storage'
        self.assertIs(archive_request(pack,EMPTY),pack)
        self.assertIn('distinct request INSTANCE',archive_request(pack,BASE)['messages'][0]['content'])
    def test_cards_splits_and_cli_development(self):
        cards=(0,1,3,4,5,6,7);self.assertEqual(gpu_ids(cards),cards)
        for bad in ((2,),(),(0,0),(8,)):
            with self.assertRaises(ValueError):gpu_ids(bad)
        self.assertTrue(set(histories()).isdisjoint(set(old_histories()+v13_histories())|set(DEVELOPMENT_HISTORIES)))
        self.assertEqual(len(schedule(cards)),120)
        self.assertEqual(len(physical_rows(cards)),8)
        cli=(Path(__file__).parent/'feedback_workflow.py').read_text()
        self.assertIn("histories()+list(__import__('feedback_protocol').DEVELOPMENT_HISTORIES)",cli)
        for h in DEVELOPMENT_HISTORIES+tuple(histories()):self.assertEqual(len(plan(h)['sessions']),20)

class GuidanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_exact_quotes_no_rewrite_or_memory_write(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'memory').mkdir();(p/'memory/MEMORY.md').write_text('order1 pending')
            (p/'memory/HISTORY.md').write_text('order0 complete')
            provider=FakeProvider([response(['long:0'])])
            guide=await MemoryOps(provider,p,p,BASE).guide([], 'continue')
            self.assertIn('order1 pending',guide)
            self.assertEqual((p/'memory/MEMORY.md').read_text(),'order1 pending')
            self.assertIn('order0 complete',provider.requests[0]['messages'][1]['content'])
            self.assertNotIn('expected_private',json.dumps(provider.requests))
    async def test_nonverbatim_rejected_once_then_stop(self):
        with tempfile.TemporaryDirectory() as d:
            bad=response(['unknown:0']);pr=FakeProvider([bad,bad])
            with self.assertRaisesRegex(RuntimeError,'guidance_protocol_failure'):
                await MemoryOps(pr,d,d,BASE).guide([],'continue')
            self.assertEqual(len(pr.requests),2)
    def test_quote_parser(self):
        sources={'long':'abc\n'+'x'*1000,'current':'continue'};cat=fragments(sources)
        self.assertEqual(checked_selection(response([]),cat),[])
        for ids in (['secret:0'],['long:0','long:0'],['long:0']*6,[{}]):
            self.assertIsNone(checked_selection(response(ids),cat))
        q=checked_selection(response(['long:0','long:1']),cat)
        self.assertTrue(all(x['text'] in sources[x['source']] for x in q))
        self.assertEqual(''.join(x['text'] for x in cat.values() if x['source']=='long'),sources['long'])

class GateTests(unittest.TestCase):
    def setUp(self):
        self.a=[dict(trial_id=str(i),status='decision_failure',correct_checkpoints=0,sessions_completed=10) for i in range(8)]
        self.b=copy.deepcopy(self.a);self.b[0].update(status='success',correct_checkpoints=7,sessions_completed=20)
    def test_full_memory_gain_needed(self):
        self.assertTrue(physical_improves(self.a,self.b));self.assertFalse(physical_improves(self.a,self.a))
        a=copy.deepcopy(self.a);a[0]['status']='execution_failure'
        self.assertFalse(physical_improves(a,self.b))
    def test_regressions_or_missing_or_invalid_not_hidden(self):
        for changes in ({'status':'infrastructure_failure'},{'sessions_completed':9}):
            b=copy.deepcopy(self.b);b[3].update(changes);self.assertFalse(physical_improves(self.a,b))
        self.assertFalse(physical_improves(self.a,self.b[:-1]))
        a=copy.deepcopy(self.a);a[1].update(status='success',correct_checkpoints=7,sessions_completed=20)
        self.assertFalse(physical_improves(a,self.b))
    def test_window_ceiling_is_not_automatic_rejection(self):
        a=dict(invalid=0,cost_complete=True,per_case={'x':2},tokens=100)
        self.assertTrue(nonregression(a,a))
        self.assertFalse(nonregression(a,dict(a,per_case={'x':1})))

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,gain):
        import learning_v14 as m
        class FakeExperiment:
            gpus=(0,1,3,4,5,6,7)
            def __init__(self):self.stop=threading.Event();self.batches=[]
            def state(self,*a,**kw):pass
            def batch(self,rows,policies,out,strict):
                self.batches.append(str(out));new='full-candidate' in str(out)
                return [dict(r,status='success' if gain and new and i==0 else 'decision_failure',
                     correct_checkpoints=7 if gain and new and i==0 else 0,
                     sessions_completed=20 if gain and new and i==0 else 10) for i,r in enumerate(rows)]
        e=FakeExperiment();candidate=copy.deepcopy(SEED);candidate['fields'].append('tool_scope')
        async def structured(*args):
            if str(args[0]).endswith('critic'):return dict(generic=True,no_task_answers=True,preserves_user_authority=True)
            return candidate
        async def windows(*a):return dict(invalid=0,cost_complete=True,per_case={'x':2},tokens=100)
        with tempfile.TemporaryDirectory() as d:
            with patch.object(m,'prepare',return_value=([],[])),patch.object(m,'structured',side_effect=structured),\
                 patch.object(m,'full_evidence',return_value=[]),patch.object(m,'batch',side_effect=windows):
                r=await m.run(Path(d)/'learning',e)
            exists=(Path(d)/'learning/accepted-policy.json').exists()
        return r,e,exists
    async def test_full_feedback_before_proposal_and_acceptance(self):
        r,e,exists=await self.exercise(True);self.assertEqual(r['status'],'accepted');self.assertTrue(exists)
        self.assertEqual(len(e.batches),2);self.assertIn('full-parent',e.batches[0])
    async def test_no_gain_bounded_stop(self):
        r,e,exists=await self.exercise(False);self.assertEqual(r['status'],'no_accepted_improvement')
        self.assertFalse(exists);self.assertEqual(len(e.batches),3);self.assertEqual(len(r['attempts']),2)
    def test_pipeline_has_no_no_gain_fallback(self):
        s=(Path(__file__).parent/'pipeline_v14.py').read_text()
        self.assertIn("'launched_test':0",s);self.assertNotIn("r['arm']!='evolved'",s)
    def test_technical_failure_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            e=Experiment(Path(d)/'run',(0,),'o','b',threading.Event());seen=[]
            def episode(row,*args):seen.append(row['trial_id']);return dict(row,status='infrastructure_failure')
            e.episode=episode
            with self.assertRaisesRegex(RuntimeError,'technical_hold'):
                e.batch([dict(trial_id=str(i),arm='memrsi',gpu=0) for i in range(3)],{},Path(d)/'batch',True)
            self.assertEqual(seen,['0'])
