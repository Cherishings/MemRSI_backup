import asyncio,json,tempfile,types,unittest,sys
from pathlib import Path
from unittest.mock import patch
import pair_episode
class LoopTest(unittest.TestCase):
 def execute(self,horizon=100,boundary_at=None):
  tmp=tempfile.TemporaryDirectory();base=Path(tmp.name);sim=base/'sim';sim.mkdir();policy=base/'policy.json';policy.write_text('{}')
  state={'steps':0,'predict':0,'observed':0,'requests':[],'receipts':[],'choose':0,'commands':[]}
  def public():return {'steps':state['steps'],'horizon':horizon,'instruction':'public goal','proprio':{},'cameras':[]}
  class Agent:
   def __init__(self,*a,**k):self.provider=types.SimpleNamespace(calls=0,wire_attempts=0,transport_retries=0)
   async def choose(self,request,**kw):
    state['requests'].append(request);state['choose']+=1
    return {'skill':'execute','instruction':'same subgoal','reason':'x'} if state['choose']==1 else {'skill':'finish','instruction':'','reason':'x'}
   async def observe(self,s):state['receipts'].append(s)
   async def close(self):pass
  def post(port,method,payload):
   if method=='reset':return {}
   if method=='observe':return {'public':public()}
   if method=='step':
    self.assertEqual(len(payload['actions']),1);state['steps']+=1
    return {'public':public(),'receipt':'public only','evaluator':{'done':state['steps']==horizon,'success':False}}
   if method=='close':
    (sim/'result.json').write_text(json.dumps({'status':'task_failure','official_check_success':False,'steps':state['steps']}));return {}
   self.fail(method)
  def predict(port,p,instruction,new_subtask=False):state['predict']+=1;state['commands'].append(instruction);return {'actions':[[0]*14 for _ in range(8)],'controller':{'name':'mock'}}
  def obs(port,p):
   state['observed']+=1;return {'boundary_ready':state['steps']==boundary_at,'observation_updates':state['observed'],'semantic_resets':0}
  mods={'setproctitle':types.SimpleNamespace(setproctitle=lambda x:None),'visual_actor':types.SimpleNamespace(VisualAgent=Agent),'rpc_client':types.SimpleNamespace(post=post,decode_cameras=lambda x:[],predict=predict,observe_step=obs),'failure_classification':types.SimpleNamespace(classify=lambda e,p:('technical_failure',type(e).__name__)),'runtime_config':types.SimpleNamespace(usage_totals=lambda x:{})}
  args=types.SimpleNamespace(arm='native',seed=1000,policy=policy,output=base/'case',controller_port=1,simulator_port=2,simulator_output=sim)
  with patch.dict(sys.modules,mods):asyncio.run(pair_episode.run(args))
  r=json.loads((args.output/'result.json').read_text());tmp.cleanup();return state,r
 def test_commits_one_subgoal_for_32_steps(self):
  s,r=self.execute();self.assertEqual(s['steps'],32);self.assertEqual(s['observed'],32);self.assertEqual(s['predict'],4);self.assertEqual(len(set(s['commands'])),1);self.assertEqual(r['status'],'task_failure');self.assertEqual(r['stop_reason'],'actor_finish')
 def test_official_horizon_never_exceeded(self):
  s,r=self.execute(10);self.assertEqual(s['steps'],10);self.assertEqual(s['observed'],10);self.assertEqual(s['choose'],1)
 def test_predicted_boundary_returns_control_not_success(self):
  s,r=self.execute(boundary_at=3);self.assertEqual(s['steps'],3);self.assertEqual(s['observed'],3);self.assertFalse(r['official_check_success']);self.assertIn('not verified',s['receipts'][0])
 def test_no_hidden_score_sent_to_actor(self):
  s,r=self.execute(10);self.assertNotIn('official_check_success',str(s['requests']+s['receipts']));self.assertNotIn('for at most eight',s['requests'][0])
if __name__=='__main__':unittest.main()
