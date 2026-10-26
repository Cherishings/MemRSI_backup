"""Audited administrative relocation only at existing child/case boundaries."""
import os,json,time,signal,subprocess,fcntl,hashlib
from pathlib import Path
ROOT=Path('/data/stormlab/xi/robot'); HERE=Path(__file__).resolve().parent
OUT=ROOT/'runs/paper-completion-20261020/gpu56-priority'; OUT.mkdir(parents=True,exist_ok=True)
def read(p):return json.loads(Path(p).read_text())
def write(p,d):
 p=Path(p); t=p.with_name(p.name+'.tmp.'+str(os.getpid()));t.write_text(json.dumps(d,indent=2));t.replace(p)
def stat(row):
 try:
  a=Path('/proc/'+str(row['pid'])+'/stat').read_text().rsplit(')',1)[1].split()
  if str(a[19])!=str(row['start_ticks']):return None
  return a
 except FileNotFoundError:return None
def living(row):
 a=stat(row);return a is not None and a[0]!='Z'
def launch(cmd,env,name):
 with (OUT/(name+'.private.log')).open('ab') as log:p=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 a=Path('/proc/'+str(p.pid)+'/stat').read_text().rsplit(')',1)[1].split()
 return {'pid':p.pid,'start_ticks':a[19],'argv':cmd,'time':time.time()}
def reap_parent(row):
 if living(row):os.kill(row['pid'],signal.SIGKILL) # parent only; its recorded child already finished
 for _ in range(30):
  if not living(row):return
  time.sleep(.1)
 raise RuntimeError('parent_still_live')
def main():
 import setproctitle;setproctitle.setproctitle('robot')
 with (OUT/'schedule.lock').open('a') as lk:
  fcntl.flock(lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
  plan=read(OUT/'plan.json'); state=read(OUT/'state.json') if (OUT/'state.json').exists() else {}
  while time.time()<1793203140:
   r=plan['rmb']
   if r.get('already_exited'):state['rmb_parent_retired']=True
   if 'rmb_parent_retired' not in state and not living(r['child']):
    if not Path(r['scored_record']).exists():raise RuntimeError('rmb_child_without_valid_terminal_requires_audit')
    reap_parent(r['parent']);state['rmb_parent_retired']=True;write(OUT/'state.json',state)
   rem=plan.get('remem')
   if rem and 'remem_restarted' not in state and not living(rem['child']):
    score=Path(rem['scored_record'])
    if not score.exists() or read(score).get('status') in ('technical_failure','unclassified_failure','paused_learning_budget'):
     state['remem_restarted']={'phase':'paused_requires_technical_audit','no_retry':True};write(OUT/'state.json',state)
    else:
     reap_parent(rem['parent'])
     state['remem_restarted']=launch(rem['argv'],plan['bench_env'],'remem5-offline-wait');write(OUT/'state.json',state)
     write(Path(rem['output'])/'coordinator.json',dict(state['remem_restarted'],gpu=5,formal_gpus=[5,7],entry=str(HERE/'study-four-gpu.py')))
   components=ROOT/'runs/paper-component-ablation-20261020'
   if not state.get('components_relocated') and all(not living(x) for x in plan['component_workers']):
    marker=read(components/'blocked.json')
    if marker.get('routing_id')!=plan['routing_id']:raise RuntimeError('component_new_blocker_requires_audit')
    claims=read(components/'claims.json')
    if any(not (components/k/'result.json').exists() for k in claims):raise RuntimeError('unfinished_component_claim_requires_audit')
    if state.get('rmb_parent_retired'):
     m=read(components/'manifest.json');m['wrapper_sha256']=hashlib.sha256((HERE/'component-ablation.py').read_bytes()).hexdigest();m['operational_gpu_migration']=str(OUT/'plan.json');write(components/'manifest.json',m)
     (components/'blocked.json').rename(OUT/'drain-block-completed.json')
     state['components_relocated']=[launch([plan['python'],str(HERE/'component-ablation.py'),'--gpu',str(g),'--output',str(components)],plan['component_env'],'component-'+str(g)) for g in [4,7]];write(OUT/'state.json',state)
   if state.get('components_relocated') and 'rmb_launched' not in state:
    state['rmb_launched']=launch(r['argv'],plan['bench_env'],'rmb6');write(OUT/'state.json',state)
    write(Path(r['output'])/'coordinator.json',dict(state['rmb_launched'],gpu=6,formal_gpus=[6,4],entry=str(HERE/'study-four-gpu.py')))
   for item in plan['paper']:
    key='paper_'+item['run_id']
    if key in state:continue
    a=stat(item['child'])
    if a is not None and a[0]=='Z':
     code=int(a[49]);reap_parent(item['parent'])
     if code!=0:state[key]={'phase':'paused_child_exit','exit_status':code,'no_retry':True}
     else:state[key]=dict(launch(item['argv'],plan['paper_env'],key),phase='physical_evaluation',gpu=item['gpu'])
     write(OUT/'state.json',state)
    elif a is None:
     state[key]={'phase':'child_disappeared_requires_audit','no_retry':True};write(OUT/'state.json',state)
   write(OUT/'progress.json',{'time':time.time(),'phase':'waiting_existing_case_boundaries' if 'rmb_launched' not in state else 'routing_applied','no_new_attempt_for_migration':True,'state_keys':list(state)})
   if 'rmb_launched' in state and (not plan.get('remem') or 'remem_restarted' in state) and all('paper_'+x['run_id'] in state for x in plan['paper']):return
   time.sleep(15)
 raise RuntimeError('start_deadline_reached')
if __name__=='__main__':
 try:main()
 except Exception as e:write(OUT/'paused.json',{'error_type':type(e).__name__,'reason':str(e) if isinstance(e,RuntimeError) else 'inspect_safe_evidence','time':time.time()});raise SystemExit(1)
