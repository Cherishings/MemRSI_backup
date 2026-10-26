"""Safe case-boundary transition to registered G/U factorial; never replay successes."""
import importlib.util,subprocess,time,json
from pathlib import Path
R=Path('/data/stormlab/xi/robot');HERE=Path(__file__).resolve().parent;OUT=R/'runs/paper-completion-20261020/gu-repair-r2-20261022';OLD=R/'runs/paper-completion-20261020/gu-repair-20261022'
s=importlib.util.spec_from_file_location('cap',R/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(s);s.loader.exec_module(cap)
from worker import verify
ROUTING='gu-core-priority-20261022'
def predecessor_ready():
 for name in ('blocked.json','paused.json'):
  if (OLD/name).exists():raise RuntimeError('predecessor_'+name)
 prior=cap.read(OLD/'manifest.json')
 if not all((OLD/j['key']/'result.json').exists() for j in prior['jobs']):return False
 scheduler=cap.read(OLD/'scheduler.json')['identity']
 if cap.alive(scheduler):return False
 if cap.read(OLD/'report.json',{}).get('phase')!='completed':raise RuntimeError('missing_predecessor_final_report')
 workers=cap.read(OLD/'launched.json')['workers']
 for g,who in workers.items():
  state=cap.read(OLD/f'worker-gpu{g}.json',{})
  if state.get('identity')!=who:raise RuntimeError('predecessor_identity_changed')
  if cap.alive(who):return False
  if state.get('phase')!='completed':raise RuntimeError('predecessor_abnormal_exit')
 for k in cap.read(OLD/'claims.json',{}):
  if not (OLD/k/'result.json').exists():raise RuntimeError('unresolved_predecessor_claim')
 for j in prior['jobs']:
  d=cap.read(OLD/j['key']/'result.json')
  if d.get('status')=='technical_failure' or d.get('error_code')=='unclassified_exception':raise RuntimeError('predecessor_technical_requires_audit')
 return True

def launch(g,me,m):
 if g==0 or g not in range(1,8):raise RuntimeError('GPU0_forbidden')
 verify(cap,OUT,m)
 with cap.locked(OUT/'dispatch.lock'):
  if (OUT/'blocked.json').exists():raise RuntimeError('new_queue_blocked')
  if (OUT/f'launch-intent-gpu{g}.json').exists() or (OUT/f'worker-gpu{g}.json').exists():raise RuntimeError('existing_launch_requires_audit')
  if all((OUT/j['key']/'result.json').exists() for j in m['jobs']):return None
  runtime=cap.read(R/'runs/paper-completion-20261020/gpu56-priority/plan.json');env=runtime['component_env'];assert env['MEMRSI_OFFLINE_WAIT']=='1'
  cmd=[runtime['python'],str(HERE/'worker.py'),'--gpu',str(g),'--output',str(OUT)]
  cap.write(OUT/f'launch-intent-gpu{g}.json',{'command':cmd,'identity':me,'time':time.time()})
  with (OUT/f'worker-gpu{g}.private.log').open('ab') as f:p=subprocess.Popen(cmd,cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
  who=cap.identity(p.pid);d=cap.read(OUT/'launched.json',{'workers':{}});d['workers'][str(g)]=who;cap.write(OUT/'launched.json',d);return who

def rmb_done():
 p=R/'runs/official-memory-adapter-v6r1-20261021/rmbench'
 if not (p/'study-complete.json').exists():return False
 if cap.read(p/'adaptation-state.json',{}).get('phase')!='complete':raise RuntimeError('RMB_inconsistent_complete')
 who=cap.read(p/'coordinator.json',{})
 return bool(who) and not cap.alive(who)

def main():
 with cap.locked(OUT/'scheduler.lock',nonblocking=True):
  me=cap.identity();cap.write(OUT/'scheduler.json',{'identity':me,'time':time.time()})
  try:
   m=cap.read(OUT/'manifest.json');verify(cap,OUT,m)
   if cap.file_sha(OLD/'manifest.json')!=m['predecessor_manifest_sha256']:raise RuntimeError('predecessor_manifest_changed')
   while time.time()<m['start_before_epoch']:
    if predecessor_ready():break
    cap.write(OUT/'progress.json',{'phase':'waiting_complete_prior_192','time':time.time()});time.sleep(15)
   else:raise RuntimeError('start_deadline')
   cap.write(OUT/'predecessor-drained.json',{'time':time.time(),'completed':sum((OLD/j['key']/'result.json').exists() for j in cap.read(OLD/'manifest.json')['jobs']),'complete_predecessor_preserved':True})
   for g in (1,2,3,4,5,7):launch(g,me,m)
   while True:
    workers=cap.read(OUT/'launched.json')['workers'];done=sum((OUT/j['key']/'result.json').exists() for j in m['jobs'])
    if (OUT/'blocked.json').exists():raise RuntimeError('new_queue_blocked_requires_audit')
    for g,who in workers.items():
     if not cap.alive(who) and cap.read(OUT/f'worker-gpu{g}.json',{}).get('phase')!='completed':raise RuntimeError('worker_abnormal_exit')
    cap.write(OUT/'progress.json',{'phase':'registered_factorial_running','completed':done,'planned':192,'gate':cap.read(OUT/'contract-gate.json',{}).get('state'),'workers':workers,'time':time.time()})
    if done==192 and not any(cap.alive(w) for w in workers.values()):
     rows={a:[] for a in m['arms']}
     for j in m['jobs']:rows[j['arm']].append({'condition':j['condition_id'],'status':cap.read(OUT/j['key']/'result.json')['status']})
     cap.write(OUT/'report.json',{'phase':'completed','arms':{a:{'terminal':len(v),'success':sum(x['status']=='success' for x in v)} for a,v in rows.items()},'rows':rows,'contract_gate':cap.read(OUT/'contract-gate.json'),'manual_not_RSI':True,'scope':m['scope'],'next_stage':m['next_stage'],'time':time.time()});return
    if '6' not in workers and time.time()<m['start_before_epoch'] and rmb_done():launch(6,me,m)
    time.sleep(15)
  except Exception as e:
   cap.write(OUT/'paused.json',{'reason':str(e),'identity':me,'time':time.time(),'automatic_retry':False});raise
if __name__=='__main__':main()
