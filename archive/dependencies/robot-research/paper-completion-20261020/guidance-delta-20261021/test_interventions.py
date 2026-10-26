import asyncio,copy,json,unittest
from types import SimpleNamespace as NS
from interventions import agent_class,candidate_policy,ARMS,PROCEDURE
P={'guidance':json.dumps({'kind':'procedure_guidance_v2','procedure':'original'}),'update':'frozen'}
class Fake:
 def __init__(self):
  self.history=[{'content':'current evidence'}];self.logs=[];self.writes={};self.calls=[];self.archives=0
  self.provider=NS(_append=lambda n,v:self.logs.append((n,v)))
  async def guide(s,c):self.calls.append((copy.deepcopy(s),c));return 'verbatim original'
  self.ops=NS(policy=copy.deepcopy(P),guide=guide)
 def _write(self,n,v):self.writes[n]=v
 async def rollover(self):self.history.clear();self.archives+=1
class Tests(unittest.TestCase):
 def test_only_g_mutated(self):
  old=copy.deepcopy(P);p=candidate_policy(P);self.assertEqual(P,old);self.assertEqual(p['update'],old['update']);self.assertNotEqual(p['guidance'],old['guidance'])
 def test_procedure_budget(self):self.assertLessEqual(len(PROCEDURE),1600)
 def test_control_is_original(self):self.assertEqual(agent_class(Fake,ARMS[0])().ops.policy,P)
 def test_treatment_is_registered(self):self.assertEqual(agent_class(Fake,ARMS[1])().ops.policy,candidate_policy(P))
 def test_both_keep_real_short_and_actor_history(self):
  for arm in ARMS:
   a=agent_class(Fake,arm)();old=copy.deepcopy(a.history);r=asyncio.run(a.ops.guide(a.history,'current'))
   self.assertEqual(r,'verbatim original');self.assertEqual(a.calls,[(old,'current')]);self.assertEqual(a.history,old)
 def test_same_boundary_cadence(self):
  for arm in ARMS:
   a=agent_class(Fake,arm)();asyncio.run(a.rollover());self.assertTrue(a.history);asyncio.run(a.rollover());self.assertEqual(a.history,[]);self.assertEqual(a.archives,1)
 def test_exposure_recorded(self):
  a=agent_class(Fake,ARMS[1])();asyncio.run(a.ops.guide(a.history,'current'));self.assertEqual(a.logs[0][1]['guidance_short_messages'],1)
 def test_unregistered_arm_blocked(self):
  with self.assertRaises(ValueError):agent_class(Fake,'unknown')
if __name__=='__main__':unittest.main()
