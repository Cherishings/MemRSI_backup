"""Small preregistered cross-platform pilot. Native now; qualified frozen RSI later.
No test feedback returns to learner. Real simulators, structured observations,
shared execution API. RobotTwin expert / RoboCasa open-loop executors disclosed.
"""
import argparse,asyncio,hashlib,json,os,signal,subprocess,sys,time,threading
from pathlib import Path
HERE=Path(__file__).resolve().parent
CORE=Path('/data/stormlab/xi/paos/worktrees/memrsi-bounded-v2_2')
sys.path.insert(0,str(CORE));sys.path.insert(0,'/data/stormlab/xi/robot/tests')
from protocol import cases,contract,BUDGET
from run_check import acquire,LEASES,lock_name
from twenty_agent import TwentyAgent
from runtime_config import usage_totals
from unified_pipeline import gateway_contract
ROOT=Path('/data/stormlab/xi/robot');STOP=threading.Event()
for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:STOP.set())

def dump(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2));t.replace(p)
def read(p):return json.loads(Path(p).read_text())
def status(out,phase,**kw):dump(out/'progress.json',dict(phase=phase,time=time.time(),**kw))

def wait_file(p,process,timeout):
 start=time.monotonic()
 while not p.exists():
  if STOP.is_set():raise RuntimeError('cancelled')
  if process.poll() is not None:raise RuntimeError('physical_worker_exit')
  if time.monotonic()-start>timeout:raise RuntimeError('physical_worker_timeout')
  time.sleep(.1)
 return read(p)

class Physical:
 def __init__(self,platform,gpu,out):
  self.out=Path(out);self.out.mkdir(parents=True);self.n=0
  e=dict(os.environ,CUDA_VISIBLE_DEVICES=str(gpu),MUJOCO_GL='egl',PYNPUT_BACKEND='dummy',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',CUDA_HOME=str(ROOT/'envs'/platform),LD_LIBRARY_PATH=str(ROOT/'envs'/platform/'lib')+':'+os.environ.get('LD_LIBRARY_PATH',''))
  self.log=(self.out/'worker.log').open('w')
  self.process=subprocess.Popen([str(ROOT/'envs'/platform/'bin/robot'),str(ROOT/'setup/bootstrap.py'),str(HERE/'physical.py'),'--platform',platform,'--output',str(self.out)],env=e,stdin=subprocess.DEVNULL,stdout=self.log,stderr=self.log,start_new_session=True)
  dump(self.out/'identity.json',dict(pid=self.process.pid,start_ticks=Path(f'/proc/{self.process.pid}/stat').read_text().split()[21]))
 def ready(self):return wait_file(self.out/'ready.json',self.process,600)
 def call(self,skill,order=0):
  n=self.n;self.n+=1;dump(self.out/f'request-{n:03d}.json',dict(skill=skill,work_order=order))
  return wait_file(self.out/f'response-{n:03d}.json',self.process,900)
 def close(self):
  if self.process.poll() is None:
   dump(self.out/f'request-{self.n:03d}.json',dict(skill='close'))
   try:self.process.wait(timeout=20)
   except subprocess.TimeoutExpired:
    os.killpg(self.process.pid,signal.SIGTERM)
    try:self.process.wait(timeout=10)
    except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
  self.log.close()

async def trial(plan,arm,policy,gpu,out):
 out=Path(out);out.mkdir(parents=True,exist_ok=False);dump(out/'private-plan.json',plan)
 actor=None;sim=None;r=dict(status='running',arm=arm,case=plan['id'],planned=plan['planned_checkpoints'],answered=0,correct=0,decisions=[],executions=[],session_switches=0)
 try:
  sim=Physical(plan['platform'],gpu,out/'physical');ready=await asyncio.to_thread(sim.ready)
  if ready['status']!='ready':raise RuntimeError('physical_startup')
  if arm=='memrsi':dump(out/'frozen-policy.json',policy)
  actor=TwentyAgent(arm,out/'agent',out/'frozen-policy.json' if policy else None,BUDGET)
  text,ids=contract(plan['platform'])
  (actor.workspace/'TOOLS.md').write_text(text);actor.action.parameters={'type':'object','properties':{'skill':{'type':'string','enum':ids},'reason':{'type':'string'}},'required':['skill','reason'],'additionalProperties':False}
  actor.provider.action_contract=text
  if actor.ops:actor.ops.action_contract=text
  for i,step in enumerate(plan['steps']):
   if STOP.is_set():raise RuntimeError('cancelled')
   if step.get('new_session'):
    await actor.rollover();r['session_switches']+=1
   observation=await asyncio.to_thread(sim.call,'observe')
   # No user intent, expected choice or evaluator completion state is in observations.
   choice=await actor.turn(step['text']+'\nCurrent observed physical state: '+json.dumps(observation['observation'],sort_keys=True),decision=True)
   correct=choice['skill']==step['expected']
   d=dict(step=i,skill=choice['skill'],expected_private=step['expected'],correct=correct,checkpoint=step['checkpoint'])
   d['observation_sha256']=hashlib.sha256(json.dumps(observation['observation'],sort_keys=True).encode()).hexdigest()
   r['decisions'].append(d)
   if step['checkpoint']:r['answered']+=1;r['correct']+=int(correct)
   if choice['skill']!='finish':
    valid=choice['skill'] in ids and (choice['skill']!='execute_current' or 'work_order' in step)
    result=await asyncio.to_thread(sim.call,choice['skill'],step.get('work_order',0)) if valid else dict(success=False,invalid_dispatch=True)
    r['executions'].append(dict(step=i,skill=choice['skill'],result=result))
    await actor.observe_only('Actual execution receipt: '+json.dumps(result,sort_keys=True))
    if not result.get('success'):
     r['status']='technical_failure' if result.get('technical_failure') else ('decision_failure' if not correct else 'physical_failure');break
   if not correct:r['status']='decision_failure';break
   dump(out/'progress.json',r)
  if r['status']=='running':r['status']='success'
 except Exception as e:
  safe={'physical_worker_exit','physical_worker_timeout','cancelled','physical_startup','provider_error','active_context_budget_exceeded','persistent_memory_budget_exhausted','native_session_archival_failed','action_protocol_failure','guidance_protocol_failure','agent_call_budget_exhausted','generation_output_limit','delta_update_protocol_failure','delta_memory_schema'}
  code=str(e) if str(e) in safe else 'unclassified_exception'
  r.update(status='technical_failure' if code in ('physical_worker_exit','physical_worker_timeout','physical_startup','provider_error','cancelled') else 'agent_failure',error_code=code,error_type=type(e).__name__)
 finally:
  if actor:
   r['logical_calls']=actor.provider.calls
   await actor.close();r.update(usage_totals(out/'agent'))
  if sim:await asyncio.to_thread(sim.close)
  r['complete_observed_trajectory_success']=r['status']=='success'
  dump(out/'result.json',r)
 return r

def main():
 p=argparse.ArgumentParser();p.add_argument('--platform',choices=['twin','casa'],required=True);p.add_argument('--gpu',type=int,choices=range(7),required=True);p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 plans=cases(a.platform);manifest=dict(version='robot-memory-pilot-v1',platform=a.platform,gpu=a.gpu,plans=plans,methods=['native','qualified_frozen_memrsi_if_available'],common_budget=BUDGET,scope='custom memory workflow built from native simulated tasks; not official benchmark score',structured_state_observation_not_visual_policy=True,executor='native_expert' if a.platform=='twin' else 'official_demonstration_action_replay',no_test_feedback_to_learning=True,no_failure_cherry_pick_retries=True)
 if (out/'manifest.json').exists() and read(out/'manifest.json')!=manifest:raise RuntimeError('changed_manifest')
 dump(out/'manifest.json',manifest)
 rows=read(out/'rows.json') if (out/'rows.json').exists() else []
 for arm in ('native','memrsi'):
  policy=None
  if arm=='memrsi':
   learn=Path(read('/data/stormlab/xi/paos/qwen-deploy/latest-memrsi-delta-v2_0r1.json')['result']);status(out,'waiting_frozen_qualified_rsi')
   while not (learn/'freeze.json').exists():
    report=read(learn/'report.json') if (learn/'report.json').exists() else {}
    if report.get('status') in ('learning_finished_no_qualified_policy','blocked'):
     dump(out/'report.json',dict(status='native_completed_rsi_unavailable',native_trials=len(rows),reason=report['status'],rsi_trials=0));return
    if STOP.wait(30):return
   policy=read(learn/'frozen-policy.json');dump(out/'rsi-source.json',dict(source=str(learn),freeze=read(learn/'freeze.json'),sha256=hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()))
  for plan in plans:
   d=out/arm/plan['id']
   if (d/'result.json').exists():continue
   if d.exists():raise RuntimeError('interrupted_trial_preserved_manual_resume_required')
   if STOP.is_set():return
   gateway_contract(STOP,lambda:status(out,'waiting_gateway'))
   used=lambda:int(subprocess.check_output(['nvidia-smi','-i',str(a.gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
   status(out,'waiting_gpu',arm=arm,case=plan['id'])
   with acquire(LEASES/lock_name(a.gpu),True,used):
    status(out,'trial',arm=arm,case=plan['id']);row=asyncio.run(trial(plan,arm,policy,a.gpu,d))
   rows.append(row);dump(out/'rows.json',rows)
   if row.get('error_code') in ('unclassified_exception','physical_worker_exit','physical_worker_timeout','physical_startup'):
    status(out,'blocked_code_or_environment',case=plan['id'],error_code=row.get('error_code'));return
 groups={}
 for arm in ('native','memrsi'):
  selected=[r for r in rows if r['arm']==arm]
  groups[arm]=dict(planned_trials=4,terminal=len(selected),success=sum(r['status']=='success' for r in selected),planned_checkpoints=12,reached=sum(r['answered'] for r in selected),correct=sum(r['correct'] for r in selected),paired_history_passes=sum(all(any(r['case']==plan['id'] and r['status']=='success' for r in selected) for plan in plans if plan['gap']==gap) for gap in (4,8)))
 dump(out/'report.json',dict(status='completed',rows=len(rows),paired_cases=len(plans),summary=groups,scope=manifest['scope']))
if __name__=='__main__':main()
