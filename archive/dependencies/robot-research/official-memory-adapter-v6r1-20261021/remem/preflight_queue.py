"""Persistent low-level preflight and real native/Mem actor entry smoke; no learning."""
import argparse,fcntl,json,os,signal,subprocess,time
from pathlib import Path
from runtime import ROOT,BASE,execution_env
from audit import code_hashes

def identity(pid):return dict(pid=pid,start_ticks=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19])
def write(path,data):
    q=path.with_suffix('.tmp');q.write_text(json.dumps(data,indent=2));q.replace(path)
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--common',type=Path,required=True);a=p.parse_args();assert a.gpu==3
    a.output.mkdir(parents=True,exist_ok=True)
    with (a.output/'preflight.lock').open('a') as own:
        fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB);write(a.output/'preflight-identity.json',dict(**identity(os.getpid()),gpu=a.gpu,source_hashes=code_hashes()))
        def stage(phase,**extra):write(a.output/'preflight-progress.json',dict(phase=phase,time=time.time(),**extra))
        with Path(f'/data/stormlab/xi/paos/qwen-deploy/gpt-gpu{a.gpu}-run.lock').open('a') as gpu:
            while True:
                try:
                    fcntl.flock(gpu,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    used=int(subprocess.check_output(['nvidia-smi','-i',str(a.gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
                    if used<=1024:break
                    fcntl.flock(gpu,fcntl.LOCK_UN)
                except BlockingIOError:pass
                stage('waiting_gpu');time.sleep(15)
            env=execution_env(a.gpu)
            for script,folder in [('initial_state_check.py','initial-state-check'),('segment_check.py','segment-check')]:
                out=a.output/folder
                if (out/'result.json').exists():
                    result=json.loads((out/'result.json').read_text())
                    if result['status']!='pass' or result['source_hashes']!=code_hashes():stage('preflight_not_passed_requires_audit',step=folder);return
                    continue
                if out.exists():stage('interrupted_preflight_requires_audit',step=folder);return
                with (a.output/(folder+'.private.log')).open('a') as log:
                    child=subprocess.Popen([str(BASE/'venv/bin/robot'),str(ROOT/script),'--output',str(out)],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,pass_fds=(gpu.fileno(),))
                stage('running',step=folder,child=identity(child.pid));rc=child.wait()
                result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else {'status':'missing_result'}
                if rc or result['status']!='pass':stage('preflight_not_passed_requires_audit',step=folder,returncode=rc,status=result['status']);return
        with (a.output/'entry-smoke.private.log').open('a') as log:
            child=subprocess.Popen(['python3',str(ROOT/'pair_queue.py'),'--output',str(a.output/'entry-smoke'),'--common',str(a.common),'--gpu',str(a.gpu),'--entry-smoke'],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        stage('real_actor_entry_smoke',child=identity(child.pid));rc=child.wait()
        entry=a.output/'entry-smoke/progress.json'
        good=entry.exists() and json.loads(entry.read_text()).get('phase')=='complete'
        rows_path=a.output/'entry-smoke/rows.json'
        rows=json.loads(rows_path.read_text()) if rows_path.exists() else []
        evaluation=dict(scope='entry preflight only; not full-task capability or paper success counts',model_logical_calls=sum(x.get('model_logical_calls',0) for x in rows),model_wire_attempts=sum(x.get('model_wire_attempts',0) for x in rows),physical_steps=sum(x.get('steps',0) for x in rows),learning_calls=0)
        write(a.output/'entry-evaluation-calls.json',evaluation)
        stage('complete_preflight_only' if good and rc==0 else 'entry_preflight_needs_audit',paired_experiments_started=False,entry_preflight_returncode=rc,evaluation=evaluation)
if __name__=='__main__':main()
