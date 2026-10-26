"""Drain the previous coordinator, preserve its entire ledger, resume in-place."""
import fcntl,hashlib,json,os,signal,subprocess,time
from pathlib import Path
from durable_queue import read
from run_queue import ROOT,BASE,env,identity
from physical_runner import same_process,AGENT_PYTHON
from replay import dump
OLD_POINTER=BASE/'qwen-deploy/latest-memrsi-stream-v1_6r1.json'
NEW_POINTER=BASE/'qwen-deploy/latest-memrsi-stream-v1_6r2.json'
def alive(record):
    try:
        s=Path(f"/proc/{record['pid']}/stat").read_text().rsplit(')',1)[1].split()
        return s[0]!='Z' and s[19]==str(record['start_ticks'])
    except FileNotFoundError:return False

def main():
    with NEW_POINTER.with_suffix('.migration.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=read(OLD_POINTER);out=Path(old['result']);pipeline=Path(old['pipeline'])
        state=out/'transport-migration-progress.json'
        current=read(NEW_POINTER)
        if current and same_process(current['coordinator']):return
        drain=read(out/'transport-drain.json')
        while any(alive(w['worker']) for w in drain['active']):
            dump(state,{'phase':'waiting_current_episodes','active':[w['trial_id'] for w in drain['active'] if alive(w['worker'])],'updated_unix':time.time()})
            time.sleep(5)
        # Pending TERM is delivered before normal coordinator work resumes.
        coord=drain['coordinator']
        if alive(coord):
            os.kill(coord['pid'],signal.SIGTERM);os.kill(coord['pid'],signal.SIGCONT)
        deadline=time.monotonic()+180
        while alive(coord):
            if time.monotonic()>deadline:raise RuntimeError('old_coordinator_did_not_exit_no_new_launch')
            time.sleep(2)
        for arm in ('native','fixed','evolved'):
            for p in (out/arm/'gpu-workers').glob('*.identity.json'):
                if alive(read(p)):raise RuntimeError('old_owned_policy_still_alive')
        # Keep metadata and source manifest of r1 unchanged. New source is an
        # operational revision, not a new experiment or a reset retry budget.
        retained={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in out.rglob('result.json')}
        audit={'version':'network-wait-v4','previous_code':old['code'],'new_code':str(ROOT),
            'same_result_directory':True,'all_attempts_preserved':True,'attempt_limit':3,
            'no_capability_failure_reruns':True,'no_exhausted_trial_reruns':True,
            'task_memory_scoring_unchanged':True,'retained_results_sha256':retained,
            'change':'network failures wait in same live model request; network pause excluded from worker wall timeout',
            'budget_change':'logical request budget unchanged at480; transport sends counted separately, including unknown billed usage; offline GET probes do not invoke a model',
            'wire_retry_may_generate_extra_tokens':True,'time':time.time()}
        dump(out/'transport-migration-v4.json',audit)
        manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in list(ROOT.glob('*.py'))+list((ROOT/'configs').glob('*.json'))}
        dump(pipeline/'code-manifest-transport-v4.json',manifest)
        # An old runtime failure report is retained by the resumed pipeline.
        with (pipeline/'pipeline.lock').open('a') as runlock,(pipeline/('transport-v4-'+str(time.time_ns())+'.log')).open('xb') as log:
            fcntl.flock(runlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            child=subprocess.Popen([AGENT_PYTHON,str(ROOT/'unified_pipeline.py'),'--output',str(out),'--after',old['after']],
                cwd=ROOT,env=env(0),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True,pass_fds=(runlock.fileno(),))
            record=dict(old,code=str(ROOT),coordinator=identity(child.pid),transport_revision='network-wait-v4',status='resumed_same_results')
            dump(NEW_POINTER,record);dump(pipeline/'launch-transport-v4.json',record)
        dump(state,{'phase':'resumed','coordinator':record['coordinator'],'updated_unix':time.time()})
        return record
if __name__=='__main__':
    try:
        result=main()
        if result:print(json.dumps(result),flush=True)
    except Exception as e:
        p=read(OLD_POINTER)
        if p:dump(Path(p['result'])/'transport-migration-error.json',{'error_type':type(e).__name__,'reason':str(e) if isinstance(e,RuntimeError) else 'inspect_migration_state','time':time.time()})
        raise
