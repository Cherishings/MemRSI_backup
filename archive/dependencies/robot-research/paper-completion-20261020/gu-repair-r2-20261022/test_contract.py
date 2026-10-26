import asyncio,json,tempfile,unittest,types
from pathlib import Path
from interventions import ARMS,agent_class,policy_for,G,U,guidance_view,receipt_text
from acceptance import inspect
class Base:
 def __init__(self):
  self.policy={'schema':1,'guidance':'old','update':'old'};self.writes={};self.events=[];self.archive_calls=0;self.guide_inputs=[]
  self.provider=types.SimpleNamespace(memory_policy=self.policy,_append=lambda n,v:self.events.append((n,v)))
  async def guide(short,current):self.guide_inputs.append((short,current));return 'verbatim'
  self.ops=types.SimpleNamespace(policy=self.policy,guide=guide)
 def _write(self,n,v):self.writes[n]=v
 async def rollover(self):self.archive_calls+=1
class Tests(unittest.TestCase):
 def test_operator_cross(self):
  p={'schema':1,'guidance':'old','update':'old'}
  for arm in ARMS:
   a=agent_class(Base,arm)();self.assertEqual(a.ops is not None,arm.startswith('g1'));self.assertEqual(bool(a.provider.memory_policy['update']),arm.endswith('u1'));self.assertEqual(a.policy,policy_for(p,arm))
  self.assertEqual(p['update'],'old')
 def test_real_short_forwarded(self):
  a=agent_class(Base,'g1_u1')();short=[{'role':'user','content':'a new public request'}];asyncio.run(a.ops.guide(short,'current'));self.assertEqual(json.loads(a.guide_inputs[0][0][0]['content']),short[0]);self.assertEqual(a.events[-1][1]['guidance_short_messages'],1)
 def test_cadence_equal_all_arms(self):
  for arm in ARMS:
   a=agent_class(Base,arm)()
   for _ in range(5):asyncio.run(a.rollover())
   self.assertEqual(a.archive_calls,2);self.assertEqual(a.actual_boundaries,2);self.assertEqual(a.requested_boundaries,5)
 def test_frozen_limits(self):
  self.assertLessEqual(len(G),1600);self.assertLessEqual(len(U),1600)
  for p in (policy_for({'schema':1},a) for a in ARMS):self.assertTrue(all(len(p[k])<=1800 for k in ('guidance','update')))
 def test_receipt_payload_unmodified(self):
  text='Actual execution receipt: {"success": false, "native_task_complete": false}'
  bound,ok=receipt_text(text,{'decision_event':7,'submitted_skill':'arbitrary_skill','expected_private':'NEVER_COPY'})
  self.assertTrue(ok);self.assertTrue(bound.startswith(text));self.assertNotIn('NEVER_COPY',bound);self.assertIn('arbitrary_skill',bound)
 def test_no_guess_missing_or_unrelated_receipt(self):
  for text,pending in [('ordinary observation',{'decision_event':1,'submitted_skill':'x'}),('Actual execution receipt: {}',None)]:self.assertEqual(receipt_text(text,pending),(text,False))
 def test_malformed_receipt_not_invented(self):
  with self.assertRaises(json.JSONDecodeError):receipt_text('Actual execution receipt: broken',{'decision_event':1,'submitted_skill':'x'})
 def test_guidance_roles_calls_preserved_no_extra_data(self):
  m={'role':'assistant','content':None,'tool_calls':[{'id':'call_public','function':{'name':'report_action','arguments':'{"skill":"x"}'}}],'hidden_score':'do_not_forward'}
  view=json.loads(guidance_view([m])[0]['content']);self.assertEqual(view['tool_calls'],m['tool_calls']);self.assertEqual(view['role'],'assistant');self.assertNotIn('hidden_score',view)
 def test_invalid_arm(self):
  with self.assertRaises(ValueError):agent_class(Base,'not_registered')
 def test_real_acceptance_no_performance_gate(self):
  with tempfile.TemporaryDirectory() as tmp:
   jobs=[{'key':a+'/case','arm':a} for a in ARMS]
   self.assertEqual(inspect(tmp,jobs)['state'],'waiting')
   for j in jobs:
    a=agent_class(Base,j['arm'])();p=Path(tmp)/j['key'];d=p/'attempt-01/agent';d.mkdir(parents=True);(p/'result.json').write_text('{"status":"decision_failure"}')
    (d/'receipt-correlations.jsonl').write_text(json.dumps({'decision_event':1,'receipt_event':2,'submitted_skill':'public_action'})+'\n');(d/'gu-contract.json').write_text(json.dumps(a.writes['gu-contract.json']));t=[{'request':{'tools':[{'function':{'name':'save_memory'}}],'messages':[{'role':'system','content':'Update procedure for the long/short memory interface.' if j['arm'].endswith('u1') else 'native'}]}}]
    if j['arm'].startswith('g1'):
     t+=[{'request':{'tools':[{'function':{'name':'select_memory_evidence'}}],'messages':[]}},{'request':{'tools':[],'messages':[{'role':'system','content':'# Selected memory evidence'}]}}];(d/'gu-exposure.jsonl').write_text(json.dumps({'guidance_short_messages':1})+'\n')
    (d/'model-trace.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in t))
   self.assertEqual(inspect(tmp,jobs)['state'],'passed')
   d=Path(tmp)/jobs[0]['key']/'attempt-01/agent/model-trace.jsonl';d.write_text(d.read_text()+json.dumps({'request':{'tools':[{'function':{'name':'select_memory_evidence'}}]}})+'\n');self.assertIn('g0_u0:guidance_not_disabled',inspect(tmp,jobs)['issues'])
if __name__=='__main__':unittest.main()
