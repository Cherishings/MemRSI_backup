import fcntl,hashlib,json,subprocess,datetime
from pathlib import Path
from run_queue import ROOT,BASE,env,identity
from replay import dump
from admission_wait import alive
from twenty_queue import PHYSICAL_FILES
from resume_support import inspect_parent,UNCHANGED_RUNTIME

def main():
    pointer=BASE/'qwen-deploy/latest-memrsi-feedback.json'
    with (BASE/'qwen-deploy/memrsi-feedback-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if pointer.exists():
            old=json.loads(pointer.read_text())
            if alive(old['coordinator']):print(json.dumps(old));return
            if old['version']!='memrsi-feedback-v1':raise RuntimeError('existing_repair_requires_inspection_no_reset')
            parent=Path(old['result']);inspect_parent(parent)
        else:raise RuntimeError('resume_parent_pointer_missing')
        core=json.loads((ROOT/'pristine-core-manifest.json').read_text())
        if core['mismatches'] or any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in core['core_sha256'].items()):raise RuntimeError('core_changed')
        oldroot=BASE/'worktrees/memrsi-feedback-v1'
        shared=list(UNCHANGED_RUNTIME)
        if any((ROOT/n).read_bytes()!=(oldroot/n).read_bytes() for n in shared):raise RuntimeError('unintended_shared_change')
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=BASE/'results'/('memrsi-feedback-v1_1-'+stamp);out.mkdir(exist_ok=False)
        dump(out/'source-audit.json',{'unchanged_core_files':len(core['core_sha256']),'unchanged_shared_files':shared,'common_runtime_change':None,'repair':'optimizer optional explanation fields and provenance-preserving orchestration resume'})
        dump(out/'code-manifest.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
        cmd=['/home/xi/envs/agent/bin/python',str(ROOT/'feedback_queue.py'),'--output',str(out/'experiment'),'--resume',str(parent),'--orders',str(BASE/'results/memrsi-history-pairs-v1-20261010T074232Z/selected-orders.json'),
            '--qualification',str(BASE/'results/memrsi-twenty-qualification-20261011T032643Z'),'--reverse',str(BASE/'results/memrsi-twenty-qualification-reverse-20261011T033434Z')]
        with (out/'queue.log').open('xb') as log:
            child=subprocess.Popen(cmd,cwd=ROOT,env=env(0),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
        record={'version':'memrsi-feedback-v1.1','resumed_from':str(parent),'code':str(ROOT),'pipeline':str(out),'result':str(out/'experiment'),'coordinator':identity(child.pid),'gpus':[0,1,6,7],'planned':120}
        dump(out/'launch.json',record);dump(pointer,record);print(json.dumps(record))
if __name__=='__main__':main()
