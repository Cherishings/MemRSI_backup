"""Launch additional registered workers on 4/7 after predecessor normal completion."""
import importlib.util,json,subprocess,time
from pathlib import Path
ROOT=Path('/data/stormlab/xi/robot');HERE=Path(__file__).resolve().parent
OUT=ROOT/'runs/paper-completion-20261020/guidance-diagnostic-20261021'
ORIGINAL=ROOT/'paper-completion-20261020/guidance-diagnostic-20261021'
AUDIT=OUT/'gpu1-7-routing-20261021'
spec=importlib.util.spec_from_file_location('cap',ROOT/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
def verify():
    m=cap.read(OUT/'manifest.json')
    for n,h in m['code_sha256'].items():
        if cap.file_sha(ORIGINAL/n)!=h:raise RuntimeError('registered_code_changed')
    if cap.digest(cap.read(OUT/'frozen-policy.json'))!=m['policy_sha256']:raise RuntimeError('policy_changed')
    for n,h in cap.read(AUDIT/'authorization.json')['routing_code_sha256'].items():
        if cap.file_sha(HERE/n)!=h:raise RuntimeError('routing_code_changed')
    return m

def launch(gpu,me):
    assert gpu in (1,2,3,4,7)
    verify()
    with cap.locked(OUT/'dispatch.lock'):
        if (OUT/'blocked.json').exists():raise RuntimeError('diagnostic_blocked')
        if (OUT/f'launch-intent-gpu{gpu}.json').exists() or (OUT/f'worker-gpu{gpu}.json').exists():raise RuntimeError('existing_gpu_launch_requires_audit')
        manifest=cap.read(OUT/'manifest.json');claims=cap.read(OUT/'claims.json',{})
        for key,claim in claims.items():
            if not (OUT/key/'result.json').exists() and not cap.alive(claim['identity']):raise RuntimeError('interrupted_claim_requires_audit')
        if all((OUT/j['key']/'result.json').exists() for j in manifest['jobs']):return None
        runtime=cap.read(ROOT/'runs/paper-completion-20261020/gpu56-priority/plan.json');env=dict(runtime['component_env'])
        assert env.get('MEMRSI_OFFLINE_WAIT')=='1'
        cmd=[runtime['python'],str(HERE/'worker-routing.py'),'--gpu',str(gpu),'--output',str(OUT)]
        cap.write(OUT/f'launch-intent-gpu{gpu}.json',{'gpu':gpu,'command':cmd,'scheduler':me,'time':time.time(),'authorization':'user_gpu1_7_20261021'})
        with (OUT/f'worker-gpu{gpu}.log').open('ab') as log:
            child=subprocess.Popen(cmd,cwd=str(ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        who=cap.identity(child.pid)
        launched=cap.read(OUT/'launched.json',{'workers':{}});launched['workers'][str(gpu)]=who;launched.update(time=time.time(),scheduler=me)
        cap.write(OUT/'launched.json',launched)
        return who

def main():
    with cap.locked(OUT/'scheduler.lock',nonblocking=True):
        me=cap.identity();cap.write(OUT/'scheduler.json',{'identity':me,'version':'gpu1-7-routing-20261021'})
        try:
            manifest=verify();plan=cap.read(OUT/'relay-plan.json');old=Path(plan['predecessor'])
            if cap.file_sha(old/'manifest.json')!=plan['predecessor_manifest_sha256']:raise RuntimeError('predecessor_manifest_changed')
            old_m=cap.read(old/'manifest.json')
            while time.time()<manifest['start_before_epoch']:
                if (old/'blocked.json').exists():raise RuntimeError('predecessor_blocked_requires_audit')
                if (OUT/'blocked.json').exists():raise RuntimeError('diagnostic_blocked_requires_audit')
                alive={str(g):cap.alive(plan['predecessor_workers'][str(g)]) for g in (4,7)}
                for g in (4,7):
                    state=cap.read(old/f'worker-gpu{g}.json',{})
                    if state.get('identity')!=plan['predecessor_workers'][str(g)]:raise RuntimeError('predecessor_identity_changed')
                    if not alive[str(g)] and state.get('phase')!='completed':raise RuntimeError('predecessor_abnormal_exit')
                missing=[j['key'] for j in old_m['jobs'] if not (old/j['key']/'result.json').exists()]
                cap.write(OUT/'relay-progress.json',{'phase':'waiting_predecessor_for_gpu4_7','identity':me,'time':time.time(),'remaining_predecessor':len(missing),'alive':alive,'active_diagnostic_workers':cap.read(OUT/'launched.json',{}).get('workers',{}),'reserved_gpu0_untouched':True})
                if not any(alive.values()):
                    if missing:raise RuntimeError('predecessor_missing_results')
                    if any(not (old/k/'result.json').exists() for k in cap.read(old/'claims.json',{})):raise RuntimeError('unresolved_predecessor_claim')
                    for job in old_m['jobs']:
                        row=cap.read(old/job['key']/'result.json')
                        if row.get('status')=='technical_failure' or row.get('error_code')=='unclassified_exception':raise RuntimeError('predecessor_technical_result')
                    break
                time.sleep(30)
            else:raise RuntimeError('registered_start_deadline_reached')
            for gpu in (4,7):launch(gpu,me)
            cap.write(OUT/'relay-progress.json',{'phase':'launched','identity':me,'time':time.time(),'workers':cap.read(OUT/'launched.json',{}).get('workers',{})})
        except Exception as e:
            cap.write(OUT/'relay-paused.json',{'reason':str(e),'identity':me,'time':time.time()});raise
if __name__=='__main__':main()
