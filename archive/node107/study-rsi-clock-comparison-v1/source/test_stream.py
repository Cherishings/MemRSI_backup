import asyncio,copy,json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from stream_design import *
from stream_replay import select,fixture,evaluate
from memory_design import update_instruction
from memory_policy import BASE,archive_request,EMPTY,digest
from memory_ops import MemoryOps
from replay import dump
from durable_queue import DurableExperiment,read
from pipeline_v15 import schedule as transfer_schedule
from feedback_protocol import schedule,plan

class StructureTests(unittest.TestCase):
 def test_splits_counts_and_no_test_outcome_selection(self):
  rows=development_rows();test=heldout_rows(schedule((0,1,2)),transfer_schedule((0,1,2),True))
  self.assertEqual(len(rows),20);self.assertEqual(len(test),96)
  self.assertFalse({r['history'] for r in rows}&{r['history'] for r in test})
  self.assertTrue(all(len(plan(r['history'])['sessions'])==20 for r in rows))
  self.assertEqual({r['gpu'] for r in rows+test},{0,1,2})
  for arm in ('before','evolved'):self.assertEqual(sum(r['arm']==arm for r in test),48)
 def test_seed_text_matches_old_manual_compiler_and_native_no_policy(self):
  p=compile_procedures(SEED_PROCEDURES)
  self.assertEqual(update_instruction(p['update']),update_instruction(BASE['update']))
  kw={'messages':[{'role':'system','content':'x'}],'tools':[{'function':{'name':'save_memory'}}]}
  self.assertIs(archive_request(kw,EMPTY),kw)
  self.assertEqual(archive_request(kw,p)['messages'],archive_request(kw,BASE)['messages'])
 def test_rule_changes_are_executable_not_just_metadata(self):
  d=dict(SEED_PROCEDURES,update='Retain authorized outstanding requests with their evidence.')
  self.assertEqual(update_instruction(compile_procedures(d)['update']),d['update'])
  self.assertNotEqual(digest(compile_procedures(d)),digest(compile_procedures(SEED_PROCEDURES)))
 def test_invalid_rules_rejected(self):
  for d in ({'guidance':'x'},dict(SEED_PROCEDURES,update=''),dict(SEED_PROCEDURES,update='x'*1601)):
   with self.assertRaises(ValueError):compile_procedures(d)
 def test_promotion_not_tie_invalid_or_regression(self):
  def r(policy,case,n):return dict(policy=policy,case=case,repeat=0,status='completed',correct=n,planned=2,model_cost_complete=True,model_input_tokens=100)
  a=[r('parent',0,0),r('candidate',0,1),r('parent',1,2),r('candidate',1,2)]
  self.assertTrue(select(a)['accepted'])
  b=copy.deepcopy(a);b[-1]['correct']=1;self.assertFalse(select(b)['accepted'])
  b=copy.deepcopy(a);b[1]['correct']=0;self.assertFalse(select(b)['accepted'])
  b=copy.deepcopy(a);b[1]['status']='invalid';self.assertFalse(select(b)['accepted'])
  b=copy.deepcopy(a);b[1]['model_input_tokens']=10000;self.assertFalse(select(b)['accepted'])

class QueueTests(unittest.TestCase):
 def test_resume_technical_only_and_total_attempt_cap(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);e=DurableExperiment(out/'ex',(0,),out/'o',out/'b',threading.Event())
   e.wait_gateway=lambda:None
   calls=[]
   def episode(row,policy,dest):
    calls.append(row['trial_id']);dest.mkdir(parents=True);res=dict(row,status='success',output=str(dest));dump(dest/'result.json',res);return res
   e.episode=episode
   rows=[dict(trial_id=str(i),arm='fixed',gpu=0) for i in range(3)]
   inherited=[dict(rows[0],status='decision_failure',output=str(out/'a')),
              dict(rows[1],status='cancelled',output=str(out/'b')),
              *[dict(rows[2],status='cancelled',output=str(out/f'c{k}')) for k in range(3)]]
   results=e.batch(rows,{'fixed':'p'},out/'batch',inherited=inherited)
   self.assertEqual(calls,['1']);self.assertEqual(results[1]['attempt'],2)
   e.batch(rows,{'fixed':'p'},out/'batch',inherited=inherited)
   self.assertEqual(calls,['1'])
 def test_crashed_attempt_count_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);e=DurableExperiment(p/'ex',(0,),p/'o',p/'b',threading.Event());e.wait_gateway=lambda:None
   rows=[dict(trial_id='x',arm='fixed',gpu=0)]
   for n in (1,2,3):dump(p/f'batch/x/attempt-{n:02d}.launch.json',dict(output=str(p/f'batch/x/attempt-{n:02d}'),attempt=n))
   e.episode=lambda *a: self.fail('exhausted trials must not restart')
   rr=e.batch(rows,{},p/'batch');self.assertEqual(rr[0]['attempt'],3)
   self.assertEqual(len(read(p/'batch/attempts.json')),3)

class GuidanceTests(unittest.IsolatedAsyncioTestCase):
 async def test_evolved_guidance_returns_exact_evidence_and_bounded_repair(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'memory').mkdir();(p/'memory/MEMORY.md').write_text('a pending')
   class Provider:
    format_repairs=0
    def __init__(self):self.requests=[]
    def _append(self,*a):pass
    async def chat(self,**kw):
     self.requests.append(kw)
     return SimpleNamespace(finish_reason='stop' if len(self.requests)==1 else 'tool_calls',tool_calls=[] if len(self.requests)==1 else [SimpleNamespace(name='select_memory_evidence',arguments={'ids':['long:0']})])
   pr=Provider();policy=compile_procedures(dict(SEED_PROCEDURES,guidance='Select relevant evidence IDs.'))
   text=await MemoryOps(pr,p,p,policy).guide([],'continue')
   self.assertIn('a pending',text);self.assertEqual(len(pr.requests),2)
   self.assertEqual(pr.requests[0]['messages'][0]['content'],'Select relevant evidence IDs.')
   self.assertTrue(all(r['tool_choice']=='required' for r in pr.requests))

class LearningTests(unittest.IsolatedAsyncioTestCase):
 async def test_no_gain_still_runs_all_batches_freezes_seed_no_candidate_fallback(self):
  import stream_learning as m
  class E:
   gpus=(2,)
   stop=threading.Event()
   def __init__(self):self.seen=[]
   def state(self,*a,**k):pass
   def wait_gateway(self):pass
   def batch(self,rows,*a):self.seen+=rows;return [dict(r,status='success',output='/fake') for r in rows]
  async def proposal(path,*a):
   if str(path).endswith('critic'):return dict(generic=True,no_task_answers=True,preserves_user_authority=True)
   return dict(SEED_PROCEDURES,update='Preserve pending authorized requests with evidence.')
  async def measurements(*a):return []
  with tempfile.TemporaryDirectory() as d:
   e=E()
   with patch.object(m,'feedback',return_value=[]),patch.object(m,'replay_sources',return_value=['/fake']),patch.object(m,'cached_structured',side_effect=proposal),patch.object(m,'paired',side_effect=measurements):
    r=await m.run(Path(d)/'learning',e,Path(d)/'b')
   self.assertEqual({r['gpu'] for r in e.seen},{2});self.assertEqual(len(e.seen),20);self.assertEqual(r['promotions'],0)
   self.assertEqual(r['frozen_sha256'],digest(compile_procedures(SEED_PROCEDURES)))
   self.assertEqual(len(list((Path(d)/'learning/snapshots').glob('*.json'))),5)
if __name__=='__main__':unittest.main()

class ReplayTests(unittest.IsolatedAsyncioTestCase):
 async def test_all_archives_rebuilt_no_gold_memory_no_counterfactual_feedback(self):
  import sys,types
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);source=p/'source';source.mkdir()
   events=[dict(id=1,text='Remember pending work.',decision_requested=False),
       dict(id=2,text='Do current job.',decision_requested=True),
       dict(id=3,text='Actual execution feedback: partial.',decision_requested=False),
       dict(id=4,text='Continue.',decision_requested=True),
       dict(id=5,text='MUST_NOT_READ_COUNTERFACTUAL_FEEDBACK',decision_requested=False)]
   (source/'received-events.jsonl').write_text('\n'.join(json.dumps(x) for x in events))
   dump(source/'result.json',dict(status='decision_failure',physical_executions=[{'result':{'success':True}}],
       decisions=[dict(session=1,skill='execute_order',expected_private='execute_order',correct=True,checkpoint=False),
                  dict(session=11,skill='finish',expected_private='serve_A',correct=False,checkpoint=True)]))
   dump(source/'rollover-1/audit.json',dict(success=True,last_received_event=3))
   observed=[];archives=[]
   class Agent:
    def __init__(self,*a):pass
    async def replay_observe(self,text,choice):observed.append((text,choice))
    async def observe_only(self,text):observed.append((text,None))
    async def turn(self,text,decision):observed.append((text,None));return {'skill':'serve_A'}
    async def rollover(self):archives.append(True)
    async def close(self):pass
   f=fixture(source)
   with patch.dict(sys.modules,{'twenty_agent':types.SimpleNamespace(TwentyAgent=Agent)}):
    r=await evaluate(f,p/'probe',compile_procedures(SEED_PROCEDURES),{})
   self.assertEqual(r['status'],'source_error_corrected');self.assertEqual(r['correct'],1)
   self.assertEqual(len(archives),1)
   self.assertNotIn('expected_private',str(observed));self.assertNotIn('MUST_NOT_READ',str(observed))

class AcceptedLearningTests(unittest.IsolatedAsyncioTestCase):
 async def test_selected_rules_guide_next_batch_and_survive_resume(self):
  import stream_learning as m
  class E:
   gpus=(2,)
   stop=threading.Event()
   def __init__(self):self.hashes=[]
   def state(self,*a,**k):pass
   def wait_gateway(self):pass
   def batch(self,rows,policies,*a):
    self.hashes.append(digest(read(policies['memrsi'])))
    return [dict(r,status='success',output='/fake') for r in rows]
  n=[0]
  async def proposal(path,*a):
   if str(path).endswith('critic'):return dict(generic=True,no_task_answers=True,preserves_user_authority=True)
   n[0]+=1;return dict(SEED_PROCEDURES,update='Retain evidence for each authorized pending request. '+('Check uncertainty. '*n[0]))
  async def measurements(*a):return []
  with tempfile.TemporaryDirectory() as d:
   e=E()
   with patch.object(m,'feedback',return_value=[]),patch.object(m,'replay_sources',return_value=['/fake']),patch.object(m,'cached_structured',side_effect=proposal),patch.object(m,'paired',side_effect=measurements),patch.object(m,'select',return_value={'accepted':True}):
    r=await m.run(Path(d)/'learning',e,Path(d)/'b')
    again=await m.run(Path(d)/'learning',e,Path(d)/'b')
   self.assertEqual(r['promotions'],4);self.assertEqual(r,again)
   self.assertEqual(len(set(e.hashes)),4);self.assertEqual(len(e.hashes),4)

class CallBudgetTests(unittest.TestCase):
 def test_learning_limit_survives_reentry_and_does_not_apply_to_physical_context(self):
  from model_provider import LEARNING_LEDGER,reserve_learning_call
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'calls.json';dump(p,{'calls':5999,'limit':6000})
   token=LEARNING_LEDGER.set(p)
   try:
    reserve_learning_call();self.assertEqual(read(p)['calls'],6000)
    with self.assertRaisesRegex(RuntimeError,'optimizer_call_budget'):reserve_learning_call()
   finally:LEARNING_LEDGER.reset(token)
   reserve_learning_call();self.assertEqual(read(p)['calls'],6000)
