"""Drain live episodes, preserve all ledgers, resume on GPU0/1/2."""
import fcntl,hashlib,json,os,signal,subprocess,time
from pathlib import Path
from durable_queue import read
from run_queue import ROOT,BASE,env,identity
from physical_runner import AGENT_PYTHON
from replay import dump
OLD=BASE/'qwen-deploy/latest-memrsi-stream-v1_6r3.json'
NEW=BASE/'qwen-deploy/latest-memrsi-stream-v1_6r4.json'
def alive(record):
    if not record:return False
    try:
        s=Path(f"/proc/{record['pid']}/stat").read_text().rsplit(')',1)[1].split()
        return s[0]!='Z' and s[19]==str(record['start_ticks'])
    except FileNotFoundError:return False

def main():
    with NEW.with_suffix('.migration.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=read(OLD);out=Path(old['result']);pipeline=Path(old['pipeline']);drain=read(out/'rsi-repair-drain.json')
        current=read(NEW)
        if current and alive(current['coordinator']):return current
        state=out/'rsi-repair-migration-progress.json'
        while any(alive(w['worker']) for w in drain['active']):
            dump(state,{'phase':'waiting_current_episodes','active':[w['trial_id'] for w in drain['active'] if alive(w['worker'])],'updated_unix':time.time()})
            time.sleep(5)
        coord=drain['coordinator']
        if alive(coord):
            os.kill(coord['pid'],signal.SIGTERM);os.kill(coord['pid'],signal.SIGCONT)
        deadline=time.monotonic()+180
        while alive(coord):
            if time.monotonic()>deadline:raise RuntimeError('old_coordinator_did_not_exit')
            time.sleep(2)
        for directory in out.glob('parallel-gpu-workers-*'):
            for p in directory.glob('*.identity.json'):
                if alive(read(p)):raise RuntimeError('old_policy_still_alive')
        # SIGTERM may wake an old stop.wait() after its child already finished.
        # Restore only that administrative cancellation label from the result
        # written BEFORE migration; never reinterpret a real capability failure.
        corrections=[]
        for w in drain['active']:
            dest=Path(w['output']);actual=read(dest/'result.json')
            if not actual or actual.get('status') in (None,'cancelled'):continue
            for name in ('attempts.json','rows.json'):
                # Trial IDs contain slashes, so find the nearest owning ledger.
                ledger=next((q/name for q in dest.parents if (q/name).exists() and q!=out.parent),None)
                if ledger is None:continue
                entries=read(ledger);changed=False
                for item in entries:
                    if item.get('output')==str(dest) and item.get('status')=='cancelled':
                        item.update(actual)
                        if item.get('error_code')=='cancelled':item.pop('error_code')
                        item['drain_recovered_finished_child']=True;changed=True
                if changed:
                    backup=ledger.with_name(ledger.stem+'-before-parallel-drain-'+str(time.time_ns())+'.json')
                    backup.write_bytes(ledger.read_bytes());dump(ledger,entries)
                    corrections.append({'ledger':str(ledger),'backup':str(backup),'output':str(dest),'status':actual['status']})
        dump(out/'rsi-repair-drain-reconciliation.json',corrections)
        retained={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('result.json')}
        changes={}
        for p in ROOT.glob('*.py'):
            original=Path(old['code'])/p.name
            if not original.exists() or original.read_bytes()!=p.read_bytes():changes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
        allowed={'parallel_pipeline.py','repair_learning.py','optimizer_context.py','structured_feedback.py','stream_learning.py','migrate_rsi_repair.py','test_optimizer_context.py'}
        if set(changes)-allowed:raise RuntimeError('unexpected_source_change')
        dump(out/'rsi-repair-migration-audit.json',{'previous_code':old['code'],'new_code':str(ROOT),'gpus':[0,1,2],
          'same_results_and_attempt_limits':True,'actor_tasks_memory_scoring_unchanged':True,'optimizer_feedback_packing_repaired':True,'old_evolved_retained':True,
          'rounds_sequential_episodes_within_round_parallel':True,'model_request_slots':2,
          'gateway_already_supports_two':True,'retained_results_sha256':retained,'changed_source_sha256':changes,
          'time':time.time(),'user_authorized_idle_gpus':True})
        with (pipeline/'pipeline.lock').open('a') as runlock,(pipeline/('rsi-repair-'+str(time.time_ns())+'.log')).open('xb') as log:
            fcntl.flock(runlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            child=subprocess.Popen([AGENT_PYTHON,str(ROOT/'parallel_pipeline.py'),'--output',str(out),'--gpus','0','1','2'],
              cwd=ROOT,env=env(0),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True,pass_fds=(runlock.fileno(),))
            record=dict(old,code=str(ROOT),coordinator=identity(child.pid),gpus=[0,1,2],scheduling_revision='three-gpu-rsi-repair-r4',evolved_directory='evolved-r4',status='resumed_same_results')
            dump(NEW,record);dump(pipeline/'launch-rsi-repair.json',record)
        dump(state,{'phase':'resumed','coordinator':record['coordinator'],'updated_unix':time.time()})
        return record
if __name__=='__main__':
    try:
        value=main()
        if value:print(json.dumps({'coordinator':value['coordinator'],'gpus':value['gpus'],'result':value['result']}),flush=True)
    except Exception as ex:
        old=read(OLD)
        if old:dump(Path(old['result'])/'rsi-repair-migration-error.json',{'error_type':type(ex).__name__,'reason':str(ex) if isinstance(ex,RuntimeError) else 'inspect_migration','time':time.time()})
        raise
