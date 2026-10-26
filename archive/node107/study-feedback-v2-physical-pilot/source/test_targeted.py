import asyncio,copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from targeted_evidence import validate_diagnosis
from targeted_learning import patched,bounded_proposal_data,target_schema
from targeted_probe import select,summarize,probe
from targeted_validation import gate
from stream_design import SEED_PROCEDURES,compile_procedures,development_rows
from optimizer_context import prepare

class MechanismTests(unittest.TestCase):
 def test_quote_diagnosis_is_hypothesis_and_no_absence_proof(self):
  p={'archive_input_excerpt':'Keep the pending request.','memory_after_excerpt':'pending request','selected_evidence_excerpt':'pending request'}
  d={'locus':'actor_usage','source_quote':'pending request','memory_quote':'pending request','guidance_quote':'pending request','explanation':'hypothesis'}
  r=validate_diagnosis(d,p);self.assertEqual(r['locus'],'actor_usage');self.assertTrue(r['absence_not_proven'])
  d['guidance_quote']='fabricated';self.assertEqual(validate_diagnosis(d,p)['locus'],'uncertain')
  d.update(locus='guidance_selection',guidance_quote='',memory_quote='');self.assertEqual(validate_diagnosis(d,p)['locus'],'uncertain')
 def test_one_arrow_only(self):
  for target in ('guidance','update'):
   other='update' if target=='guidance' else 'guidance'
   p,c=patched(SEED_PROCEDURES,{target:'Preserve verified evidence and distinguish uncertainty.','rationale':'Generic.'},target)
   self.assertEqual(p[other],SEED_PROCEDURES[other]);self.assertNotEqual(p[target],SEED_PROCEDURES[target])
   with self.assertRaises(ValueError):patched(SEED_PROCEDURES,{target:'x',other:'y','rationale':'bad'},target)
 def test_history_group_split(self):
  rs=development_rows();self.assertFalse({r['history'] for r in rs[:16]}&{r['history'] for r in rs[16:]})
 def test_selection_aggregate_not_one_lucky_win(self):
  def make(a,b):
   rows=[]
   for i,(old,new) in enumerate(zip(a,b)):
    for k,c in [('parent',old),('candidate',new)]:rows.append(dict(fixture=str(i//3),repeat=i%3,policy=k,status='answered',correct=c,all_costs_known=True,all_attempt_calls=5,all_attempt_cost_tokens=50))
   return rows
  rows=make([1,0,0,1,1,0],[1,1,1,1,0,1]);self.assertTrue(select(rows)['accepted'])
  self.assertFalse(select(make([0,0,0],[0,0,0]))['accepted'])
  self.assertFalse(select(make([1,1,1,0,0,0,0,0,0],[0,0,0,1,1,1,1,1,1]))['accepted'])
  rows[0]['status']='technical_failure';self.assertFalse(select(rows)['accepted'])
 def test_missing_token_usage_does_not_erase_valid_decision_but_cost_calls_count(self):
  rows=[dict(fixture='f',repeat=0,policy=k,status='answered',correct=c,all_costs_known=False,all_attempt_calls=n,all_attempt_cost_tokens=0) for k,c,n in [('parent',False,5),('candidate',True,7)]]
  s=select(rows);self.assertTrue(s['accepted']);self.assertFalse(s['cost_complete'])
  rows[1]['all_attempt_calls']=8;self.assertFalse(select(rows)['accepted'])
 def test_sealed_validation_requires_all_pairs(self):
  rows=[dict(case=str(i),repeat=j,policy=k,status='completed',correct=2,planned=2,all_attempt_calls=5,cost_known=True,all_attempt_tokens=50) for i in range(2) for j in range(2) for k in ('parent','candidate')]
  self.assertTrue(gate(rows,2)['passed']);rows[-1]['status']='invalid';self.assertFalse(gate(rows,2)['passed'])

class RetryTests(unittest.IsolatedAsyncioTestCase):
 async def test_technical_retries_bounded_and_not_ability_best_of(self):
  with tempfile.TemporaryDirectory() as d:
   calls=[]
   async def attempt(f,out,p,b):
    calls.append(str(out));return dict(fixture='f',status='technical_failure' if len(calls)==1 else 'answered',correct=False,calls=2,model_cost_complete=False,model_input_tokens=1,model_output_tokens=1)
   with patch('targeted_probe.attempt',attempt):
    r=await probe({'id':'f'},Path(d)/'p',{}, {},lambda:None)
    self.assertEqual(len(calls),2);self.assertEqual(r['all_attempt_calls'],4)
    await probe({'id':'f'},Path(d)/'p',{}, {},lambda:None);self.assertEqual(len(calls),2)
  with tempfile.TemporaryDirectory() as d:
   async def fail(*a):return dict(status='technical_failure',correct=False,calls=1)
   with patch('targeted_probe.attempt',fail):r=await probe({'id':'f'},Path(d),{}, {},lambda:None)
   self.assertEqual(r['attempts'],3)
if __name__=='__main__':unittest.main()

class LearningIntegrationTests(unittest.IsolatedAsyncioTestCase):
 async def test_two_cycles_execute_new_parent_and_no_heldout_read(self):
  import targeted_learning as m
  class E:
   def __init__(self):self.seen=[]
   def state(self,*a,**k):pass
   def wait_gateway(self):pass
   def batch(self,rows,policies,out):
    self.seen.append(json.loads(Path(policies['memrsi']).read_text()))
    return [dict(r,status='success',output='/development-only/'+r['trial_id']) for r in rows]
  async def submission(path,system,data,schema,wait):
   if str(path).endswith('critic'):return dict(generic=True,no_task_answers=True,preserves_user_authority=True)
   k=data['target_operator'];return {k:'Use verified provenance and distinguish intentions from completed feedback. '+('Next.' if len(e.seen)>1 else ''),'rationale':'generic'}
  async def measure(fs,out,p,c,b,w):
   return [dict(fixture='f',repeat=i,policy=k,status='answered',correct=k=='candidate',all_costs_known=True,all_attempt_calls=3,all_attempt_cost_tokens=30) for i in range(3) for k in ('parent','candidate')]
  with tempfile.TemporaryDirectory() as d:
   e=E()
   with patch.object(m,'fixtures',side_effect=lambda rows:([{'id':r['trial_id']} for r in rows],[])),patch.object(m,'diagnose',return_value=[]),patch.object(m,'bounded_proposal_data',side_effect=lambda target,*a:{'target_operator':target}),patch.object(m,'cached_structured',submission),patch.object(m,'paired',measure):
    r=await m.run(Path(d)/'new',e,{},Path(d)/'old')
   self.assertEqual(len(e.seen),2);self.assertNotEqual(e.seen[0],e.seen[1]);self.assertGreaterEqual(r['promotions'],1)
   manifest=json.loads((Path(d)/'new/manifest.json').read_text());self.assertEqual(len(manifest['development_ids']),16);self.assertEqual(len(manifest['reserved_validation_ids']),4)

class StartupTests(unittest.TestCase):
 def test_policy_log_directory_exists_before_acquire(self):
  import targeted_pipeline as m
  with tempfile.TemporaryDirectory() as tmp:
   def runner(path,stop,gpus):
    self.assertTrue(Path(path).is_dir());self.assertEqual(gpus,(0,1,2));return path
   with patch.object(m,'PhysicalRunner',runner):
    a=m.make_runner(Path(tmp),None);b=m.make_runner(Path(tmp),None);self.assertNotEqual(a,b)
