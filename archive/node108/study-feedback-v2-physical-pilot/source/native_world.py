"""Persistent native scene; exact native instruction, observations and policy cadence."""
import collections,contextlib,hashlib,json,sys,traceback,os
from pathlib import Path
import numpy as np
from openpi_client import image_tools,websocket_client_policy
from check_case import load_official,RecordingEnv,released
from retry_recovery import release_and_verify,release_and_lift
from run_queue import dump
from paired_sampling import BASE_SEED,sampling_seed,query_hash,array_hash

class NativeWorld:
 def __init__(self,req):
  self.out=Path(req['output']);self.out.mkdir(parents=True,exist_ok=False)
  self.sampling_identity=(int(os.environ.get('PAOS_PHYSICAL_SEED',BASE_SEED)),req['suite'],req['task_id'],req['init'])
  self.m=load_official();suite=self.m.benchmark.get_benchmark_dict()[req['suite']]();self.task=suite.get_task(req['task_id'])
  if self.task.name!=req['task_name']:raise RuntimeError('task_identity_mismatch')
  base,_=self.m._get_libero_env(self.task,256,0);self.env=RecordingEnv(base,self.out);self.calls=0
  self.execution_index=0
  self.partial_task=(req['suite']=='libero_10' and req['task_id']==6)
  self.horizon=520 if req['suite']=='libero_10' else 400
  # Accommodate the already specified three attempts plus bounded recovery/release.
  # Per-attempt policy budget is unchanged; no reset or object relocation.
  self.total_step_cap=10+3*(self.horizon+30)+2*(60+30)
  # A partial task may be dispatched twice; each segment retains the same three-attempt limit.
  if self.partial_task:self.total_step_cap*=2
  base.env.horizon=self.total_step_cap+1
  self.env.reset();self.env.set_init_state(suite.get_task_init_states(req['task_id'])[req['init']])
  for _ in range(10):self.env.step(self.m.LIBERO_DUMMY_ACTION)
  self.client=websocket_client_policy.WebsocketClientPolicy('127.0.0.1',req['port'])
  dump(self.out/'initial.json',dict(self.observe(),instruction=self.task.language,task_name=self.task.name))
 def observe(self):
  e=self.env.env.env;objects={}
  for name,obj in e.objects_dict.items():
   body=e.sim.model.body_name2id(obj.root_body)
   objects[name]={'position_xyz_m':[round(float(x),4) for x in e.sim.data.body_xpos[body]],'held_by_gripper':bool(e._check_grasp(e.robots[0].gripper,obj.contact_geoms))}
  return {'scene_observation':{'objects':objects},'steps':self.env.steps,'policy_calls':self.calls,'reset_count':1,'simulator_horizon':self.env.env.env.horizon,'max_total_action_steps':self.total_step_cap,
   'state_sha256':hashlib.sha256(self.env.sim.get_state().flatten().tobytes()).hexdigest()}
 def native_goal(self):return bool(self.env.env.env._check_success())
 def satisfied(self):return self.native_goal() and released(self.env.env)
 def step(self,action,phase):
  self.env.step(np.asarray(action).tolist())
  with (self.out/'recovery-actions.jsonl').open('a') as f:f.write(json.dumps({'step':self.env.steps,'phase':phase})+'\n')
 def components(self):
  if not self.partial_task:return {}
  e=self.env.env.env
  return {'white_mug_on_plate':bool(e._eval_predicate(['on','porcelain_mug_1','plate_1'])),
          'pudding_right_of_plate':bool(e._eval_predicate(['on','chocolate_pudding_1','living_room_table_plate_right_region']))}
 def execute(self,stop_after_one=False):
  self.execution_index+=1
  if stop_after_one and not self.partial_task:raise RuntimeError('partial_stop_unsupported_task')
  component_start=self.components()
  if stop_after_one and any(component_start.values()):raise RuntimeError('partial_start_already_satisfied')
  def segment_goal():return sum(self.components().values())==1 if stop_after_one else self.native_goal()
  def segment_satisfied():return segment_goal() and released(self.env.env)
  attempts=[];recoveries=[];success=False
  if segment_satisfied():return {'success':True,'native_task_complete':self.satisfied(),'components_before':component_start,'components_after':self.components(),'execution_index':self.execution_index,'stop_after_one':stop_after_one,'already_satisfied':True,'attempts':[],'after':self.observe()}
  for attempt in range(1,4):
   start=self.env.steps;plan=collections.deque();confirm=None;reached=False;chunk=0
   for _ in range(self.horizon):
    if not plan:
     obs=self.env.last
     query={'observation/image':image_tools.convert_to_uint8(image_tools.resize_with_pad(np.ascontiguousarray(obs['agentview_image'][::-1,::-1]),224,224)),
      'observation/wrist_image':image_tools.convert_to_uint8(image_tools.resize_with_pad(np.ascontiguousarray(obs['robot0_eye_in_hand_image'][::-1,::-1]),224,224)),
      'observation/state':np.concatenate((obs['robot0_eef_pos'],self.m._quat2axisangle(obs['robot0_eef_quat']),obs['robot0_gripper_qpos'])),
      'prompt':str(self.task.language)}
     seed=sampling_seed(*self.sampling_identity,attempt+(self.execution_index-1)*3,chunk)
     expected_input=query_hash(query)
     if self.calls==0:np.savez_compressed(self.out/'first-policy-input.npz',**query)
     response=self.client.infer(dict(query,_paired_sampling_seed=seed));actions=response['actions']
     audit=response.get('paired_sampling',{})
     if audit.get('seed')!=seed or audit.get('input_sha256')!=expected_input or audit.get('actions_sha256')!=array_hash(actions):
      raise RuntimeError('paired_policy_audit_mismatch')
     with (self.out/'policy-sampling.jsonl').open('a') as f:
      f.write(json.dumps(dict(audit,execution_index=self.execution_index,attempt=attempt,chunk=chunk,step=self.env.steps))+'\n')
     if self.calls==0:np.save(self.out/'first-policy-actions.npy',actions)
     self.calls+=1;chunk+=1
     if len(actions)<5:raise RuntimeError('invalid_policy_chunk')
     plan.extend(actions[:5])
    a=np.asarray(plan.popleft())
    if a.shape!=(7,) or not np.isfinite(a).all():raise RuntimeError('invalid_action')
    self.env.step(a.tolist())
    if segment_goal():
     reached=True;confirm=release_and_verify(self.env.env.env.robots[0].controller,self.step,segment_satisfied);success=confirm['success'];break
   attempts.append({'attempt':attempt,'start_step':start,'end_step':self.env.steps,'native_goal_reached':reached,'release_confirmation':confirm,'success':success})
   dump(self.out/('attempts-%d.json'%self.execution_index),{'attempts':attempts,'recoveries':recoveries})
   if success:break
   if attempt<3:
    recovery=release_and_lift(self.env.env.env.robots[0].controller,self.step,segment_satisfied);recoveries.append(recovery)
    if recovery['goal_completed']:
     confirm=release_and_verify(self.env.env.env.robots[0].controller,self.step,segment_satisfied)
     if confirm['success']:success=True;recoveries[-1]['release_confirmation']=confirm;break
  r={'success':success,'native_task_complete':self.satisfied(),'stop_after_one':stop_after_one,'components_before':component_start,'components_after':self.components(),'execution_index':self.execution_index,'attempts':attempts,'recoveries':recoveries,'instruction':self.task.language,'after':self.observe()}
  dump(self.out/('execution-%d.json'%self.execution_index),r);dump(self.out/'execution.json',r);return r
 def close(self):self.env.finish()

def main():
 w=None
 try:
  for line in sys.stdin:
   try:
    req=json.loads(line)
    with contextlib.redirect_stdout(sys.stderr):
     if req['op']=='initialize':w=NativeWorld(req);r=w.observe()
     elif req['op']=='observe':r=w.observe()
     elif req['op']=='execute':r=w.execute(req.get('stop_after_one',False))
     elif req['op']=='close':r=w.observe();w.close();w=None
     else:raise ValueError('unknown_operation')
    print(json.dumps({'ok':True,'result':r}),flush=True)
    if req['op']=='close':break
   except Exception as e:
    traceback.print_exc(file=sys.stderr);print(json.dumps({'ok':False,'error_type':type(e).__name__}),flush=True);break
 finally:
  if w:
   with contextlib.redirect_stdout(sys.stderr):w.close()
if __name__=='__main__':main()
