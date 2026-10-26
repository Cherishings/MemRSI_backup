import datetime,fcntl,hashlib,json,subprocess
from pathlib import Path
from replay import dump
from run_queue import ROOT,BASE,env,identity
from physical_runner import AGENT_PYTHON,same_process
from queue012 import COMPARISON,EVOLUTION,GPUS,recovery_plan
POINTER=BASE/'qwen-deploy/latest-memrsi-012.json'
def preflight():
    for parent in (COMPARISON,EVOLUTION):
        launch=json.loads((parent.parent/'launch.json').read_text())
        if same_process(launch['coordinator']):raise RuntimeError('parent_alive')
        for p in (parent/'gpu-workers').glob('*.identity.json'):
            if same_process(json.loads(p.read_text())):raise RuntimeError('parent_policy_alive')
    old=BASE/'worktrees/memrsi-feedback-v1_5r1'
    for p in old.glob('*.py'):
        if p.read_bytes()!=(ROOT/p.name).read_bytes():raise RuntimeError('inherited_source_changed')
    rows,attempts,_=recovery_plan()
    return dict(gpus=list(GPUS),transfer_trials=24,recovery_trials=len(rows),prior_attempts=len(attempts),inherited_sources_unchanged=True)
def main():
    audit=preflight()
    with (BASE/'qwen-deploy/memrsi-012-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if POINTER.exists():print(json.dumps({'status':'existing_run_no_duplicate','pointer':str(POINTER)}));return
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out=BASE/'results'/('memrsi-012-'+stamp);out.mkdir();dump(out/'preflight.json',audit)
        dump(out/'code-manifest.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')})
        record=dict(code=str(ROOT),pipeline=str(out),result=str(out/'experiment'),gpus=list(GPUS),status='launching')
        dump(POINTER,record)
        with (out/'pipeline.lock').open('a') as lease,(out/'queue.log').open('xb') as log:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            child=subprocess.Popen([AGENT_PYTHON,str(ROOT/'queue012.py'),'--output',str(out/'experiment')],
                cwd=ROOT,env=env(0),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,pass_fds=(lease.fileno(),))
            record.update(status='started',coordinator=identity(child.pid));dump(POINTER,record);dump(out/'launch.json',record)
        print(json.dumps(record))
if __name__=='__main__':main()
