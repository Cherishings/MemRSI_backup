"""Finite continuation after all registered Guidance diagnostics finish normally."""
import importlib.util,subprocess,time
from pathlib import Path
ROOT=Path('/data/stormlab/xi/robot');HERE=Path(__file__).resolve().parent
OUT=ROOT/'runs/paper-completion-20261020/guidance-delta-20261021'
spec=importlib.util.spec_from_file_location('cap',ROOT/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
from worker import verify

def predecessor_ready(old,manifest):
    if cap.file_sha(old/'manifest.json')!=manifest['predecessor_manifest_sha256']:raise RuntimeError('predecessor_manifest_changed')
    for name in ('blocked.json','relay-paused.json'):
        if (old/name).exists():raise RuntimeError('predecessor_'+name)
    prior=cap.read(old/'manifest.json');missing=[j['key'] for j in prior['jobs'] if not (old/j['key']/'result.json').exists()]
    if missing:return False,len(missing)
    relay=cap.read(old/'scheduler.json',{}).get('identity')
    if relay is None:raise RuntimeError('missing_predecessor_scheduler_identity')
    if cap.alive(relay):return False,0
    if cap.read(old/'relay-progress.json',{}).get('phase')!='launched':raise RuntimeError('predecessor_scheduler_not_complete')
    workers=cap.read(old/'launched.json',{}).get('workers',{})
    if not workers:raise RuntimeError('missing_predecessor_workers')
    any_alive=False
    for gpu,who in workers.items():
        state=cap.read(old/f'worker-gpu{gpu}.json',{})
        if state.get('identity')!=who:raise RuntimeError('predecessor_worker_identity_changed')
        alive=cap.alive(who);any_alive|=alive
        if not alive and state.get('phase')!='completed':raise RuntimeError('predecessor_abnormal_exit')
    if any_alive:return False,0
    for key in cap.read(old/'claims.json',{}):
        if not (old/key/'result.json').exists():raise RuntimeError('predecessor_unresolved_claim')
    for j in prior['jobs']:
        r=cap.read(old/j['key']/'result.json')
        if r.get('status')=='technical_failure' or r.get('error_code')=='unclassified_exception':raise RuntimeError('predecessor_technical_result')
    return True,0

def launch(gpu,me,manifest):
    if gpu not in (1,2,3,4,7):raise RuntimeError('gpu_not_authorized_for_queue')
    verify(cap,OUT,manifest)
    with cap.locked(OUT/'dispatch.lock'):
        if (OUT/'blocked.json').exists():raise RuntimeError('new_queue_blocked')
        if (OUT/f'launch-intent-gpu{gpu}.json').exists() or (OUT/f'worker-gpu{gpu}.json').exists():raise RuntimeError('existing_launch_requires_audit')
        for key,claim in cap.read(OUT/'claims.json',{}).items():
            if not (OUT/key/'result.json').exists() and not cap.alive(claim['identity']):raise RuntimeError('interrupted_claim_requires_audit')
        if all((OUT/j['key']/'result.json').exists() for j in manifest['jobs']):return None
        runtime=cap.read(ROOT/'runs/paper-completion-20261020/gpu56-priority/plan.json');env=dict(runtime['component_env'])
        if env.get('MEMRSI_OFFLINE_WAIT')!='1':raise RuntimeError('offline_wait_required')
        cmd=[runtime['python'],str(HERE/'worker.py'),'--gpu',str(gpu),'--output',str(OUT)]
        cap.write(OUT/f'launch-intent-gpu{gpu}.json',{'gpu':gpu,'scheduler':me,'time':time.time(),'command':cmd})
        with (OUT/f'worker-gpu{gpu}.log').open('ab') as log:
            proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        who=cap.identity(proc.pid);launched=cap.read(OUT/'launched.json',{'workers':{}});launched['workers'][str(gpu)]=who
        cap.write(OUT/'launched.json',launched);return who

def main():
    with cap.locked(OUT/'scheduler.lock',nonblocking=True):
        me=cap.identity();cap.write(OUT/'scheduler.json',{'identity':me})
        try:
            m=cap.read(OUT/'manifest.json');verify(cap,OUT,m);old=Path(m['predecessor'])
            while time.time()<m['start_before_epoch']:
                ready,left=predecessor_ready(old,m)
                cap.write(OUT/'relay-progress.json',{'phase':'waiting_registered_diagnostic','remaining_predecessor':left,'identity':me,'time':time.time()})
                if ready:break
                time.sleep(30)
            else:raise RuntimeError('registered_start_deadline_reached')
            for gpu in (1,2,3,4,7):launch(gpu,me,m)
            cap.write(OUT/'relay-progress.json',{'phase':'launched','identity':me,'time':time.time(),'workers':cap.read(OUT/'launched.json',{}).get('workers',{})})
        except Exception as e:
            cap.write(OUT/'relay-paused.json',{'reason':str(e),'identity':me,'time':time.time()});raise
if __name__=='__main__':main()
