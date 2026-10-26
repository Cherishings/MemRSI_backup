"""Native evaluator with task/init filtering; separately labelled continuous run."""
import argparse,collections,importlib.util,json,time,hashlib
from pathlib import Path
import numpy as np
import cv2
from openpi_client import image_tools,websocket_client_policy
from run_queue import dump
from retry_recovery import release_and_verify,release_and_lift
OFFICIAL=Path('/data/stormlab/xi/openpi/examples/libero/main.py')
PRED={'wine':['on','wine_bottle_1','wine_rack_1_top_region'],'bowl':['in','akita_black_bowl_1','wooden_cabinet_1_top_region']}
NAMES={'wine':'put_the_wine_bottle_on_the_rack','bowl':'open_the_top_drawer_and_put_the_bowl_inside'}

def goal(env,name):return bool(env.env._eval_predicate(PRED[name]))
def released(env):
 e=env.env
 return not any(e._check_grasp(e.robots[0].gripper,obj.contact_geoms) for obj in e.objects_dict.values())
class RecordingEnv:
 def __init__(self,env,out):
  self.env=env;self.out=out;self.steps=0;self.last=None;self.actions=[];self.native_success=False
  self.video=cv2.VideoWriter(str(out/'full-speed.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),20.,(512,256))
  if not self.video.isOpened():raise RuntimeError('video_writer_failed')
 def __getattr__(self,name):return getattr(self.env,name)
 def set_init_state(self,state):
  np.save(self.out/'requested-initial-state.npy',state)
  obs=self.env.set_init_state(state);self.last=obs
  np.save(self.out/'initial-state.npy',self.env.sim.get_state().flatten());return obs
 def step(self,action):
  result=self.env.step(action);self.last=result[0];self.steps+=1;self.actions.append(np.asarray(action))
  self.native_success=self.native_success or bool(result[2])
  frame=np.hstack([self.last['agentview_image'][::-1],self.last['robot0_eye_in_hand_image'][::-1]])
  self.video.write(np.ascontiguousarray(frame[:,:,::-1]))
  if self.steps%20==0:dump(self.out/'progress.json',{'steps':self.steps,'native_success_seen':self.native_success})
  return result
 def finish(self):
  self.video.release();np.save(self.out/'actions.npy',np.asarray(self.actions));np.save(self.out/'final-state.npy',self.env.sim.get_state().flatten())
  self.env.close()

def load_official():
 s=importlib.util.spec_from_file_location('official_libero',OFFICIAL);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def run_single(m,a,out):
 suite=m.benchmark.get_benchmark_dict()[a.suite]();task=suite.get_task(a.task_id);saved=m.benchmark.get_benchmark_dict
 class Selection:
  n_tasks=1
  def get_task(self,index):return task
  def get_task_init_states(self,index):return suite.get_task_init_states(a.task_id)[a.init:a.init+1]
 m.benchmark.get_benchmark_dict=lambda:dict(saved(),**{a.suite:Selection})
 original=m._get_libero_env;captures=[]
 def wrap(task,resolution,seed):
  env,language=original(task,resolution,seed);recorded=RecordingEnv(env,out);captures.append(recorded);return recorded,language
 m._get_libero_env=wrap
 args=m.Args(host='127.0.0.1',port=a.port,task_suite_name=a.suite,num_trials_per_task=1,seed=0,video_out_path=str(out/'official-export'))
 try:
  # The actual upstream evaluation function is executed without source edits.
  m.eval_libero(args)
  if not captures:raise RuntimeError('no_environment_created')
  e=captures[0];files=list((out/'official-export').glob('*_success.mp4'))
  # Official score is already fixed. Separate feasibility check verifies released placement.
  released_at_official_stop=released(e.env)
  confirm=release_and_verify(e.env.env.robots[0].controller,lambda action,phase:e.step(np.asarray(action).tolist()),lambda:bool(e.env.env._check_success()) and released(e.env)) if files else {'success':False,'steps':0}

  return {'status':'success' if files else 'execution_failure','native_success':bool(files),'task_name':task.name,'instruction':task.language,
    'steps':e.steps,'released_at_official_stop':released_at_official_stop,'release_confirmation':confirm,'selection_success':bool(files) and confirm['success'],'released_at_stop':released(e.env),'initial_state_sha256':hashlib.sha256(np.load(out/'initial-state.npy').tobytes()).hexdigest(),
    'official_source_sha256':hashlib.sha256(OFFICIAL.read_bytes()).hexdigest(),'modifications':'Task/init selection and recording only during official eval. After official score is fixed, a separately scored release confirmation checks feasibility. Official eval loop and official policy server. Environment seed explicitly 0. No recovery, handoff, or stability requirement in official success score.'}
 finally:
  for e in captures:e.finish()

def run_continuous(m,a,out):
 suite=m.benchmark.get_benchmark_dict()['libero_goal']();tasks={}
 for name,taskname in NAMES.items():
  idx=next(i for i in range(suite.n_tasks) if suite.get_task(i).name==taskname);tasks[name]=(idx,suite.get_task(idx))
 idx,task=tasks['wine'];base,_=m._get_libero_env(task,256,0);base.env.horizon=5000;e=RecordingEnv(base,out)
 stages=[];calls=0
 try:
  e.reset();obs=e.set_init_state(suite.get_task_init_states(idx)[a.init])
  for _ in range(10):obs=e.step(m.LIBERO_DUMMY_ACTION)[0]
  client=websocket_client_policy.WebsocketClientPolicy('127.0.0.1',a.port)
  def step(action,phase):
   e.step(np.asarray(action).tolist())
   with (out/'recovery-actions.jsonl').open('a') as f:f.write(json.dumps({'step':e.steps,'phase':phase})+'\n')
  for name in ['wine','bowl']:
   row={'skill':name,'instruction':tasks[name][1].language,'attempts':[],'recoveries':[]};stages.append(row);ok=False
   for attempt in range(1,6):
    start=e.steps;plan=collections.deque()
    while e.steps-start<300:
     if not plan:
      obs=e.last
      request={'observation/image':image_tools.convert_to_uint8(image_tools.resize_with_pad(np.ascontiguousarray(obs['agentview_image'][::-1,::-1]),224,224)),
       'observation/wrist_image':image_tools.convert_to_uint8(image_tools.resize_with_pad(np.ascontiguousarray(obs['robot0_eye_in_hand_image'][::-1,::-1]),224,224)),
       'observation/state':np.concatenate((obs['robot0_eef_pos'],m._quat2axisangle(obs['robot0_eef_quat']),obs['robot0_gripper_qpos'])),
       'prompt':tasks[name][1].language}
      plan.extend(client.infer(request)['actions'][:5]);calls+=1
     e.step(plan.popleft().tolist())
     if goal(base,name):
      v=release_and_verify(base.env.robots[0].controller,step,lambda:goal(base,name) and released(base))
      row.setdefault('release_checks',[]).append(v);ok=v['success'];plan.clear()
      if ok:break
    row['attempts'].append({'attempt':attempt,'start_step':start,'end_step':e.steps,'goal_released_stably':ok})
    if ok:break
    if attempt<5:
     x=release_and_lift(base.env.robots[0].controller,step,lambda:goal(base,name) and released(base));row['recoveries'].append(x)
     if x['goal_completed']:
      v=release_and_verify(base.env.robots[0].controller,step,lambda:goal(base,name) and released(base));ok=v['success'];row.setdefault('release_checks',[]).append(v)
      if ok:break
   row['success']=ok;row['goals_after']={n:goal(base,n) for n in PRED}
   dump(out/'stage-progress.json',{'stages':stages,'steps':e.steps,'policy_calls':calls})
   if not ok:break
  final={n:goal(base,n) for n in PRED};all_good=len(stages)==2 and all(s['success'] for s in stages) and all(final.values()) and released(base)
  return {'status':'success' if all_good else 'execution_failure','stages':stages,'final_goals':final,'released_at_stop':released(base),'steps':e.steps,'policy_calls':calls,
    'scope':'Continuous wine then bowl from native wine-task initial state. No reset between tasks, no scripted return pose. Native prompts and policy; explicit bounded release/recovery. This is NOT an unmodified official benchmark episode.'}
 finally:e.finish()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--mode',choices=['single','continuous'],required=True);p.add_argument('--suite',default='libero_goal');p.add_argument('--task-id',type=int,default=0);p.add_argument('--init',type=int,required=True);a=p.parse_args()
 out=Path(a.output);out.mkdir(parents=True,exist_ok=False);start=time.time()
 try:r=run_single(load_official(),a,out) if a.mode=='single' else run_continuous(load_official(),a,out)
 except Exception as ex:
  import traceback;traceback.print_exc();r={'status':'infrastructure_failure','error_type':type(ex).__name__}
 r.update(mode=a.mode,suite=a.suite,task_id=a.task_id,init=a.init,elapsed_seconds=time.time()-start);dump(out/'result.json',r)
