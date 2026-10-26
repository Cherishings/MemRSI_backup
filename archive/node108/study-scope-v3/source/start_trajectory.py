"""Idempotent start/resume; only authorized GPU0–6, one lifetime attempt ledger."""
import argparse,datetime,fcntl,json,subprocess
from pathlib import Path
from replay import dump
from run_queue import ROOT,BASE,env,identity
from physical_runner import AGENT_PYTHON,same_process
from durable_queue import read

def main(a):
    gpus=tuple(map(int,a.gpus.split(',')))
    if not gpus or len(set(gpus))!=len(gpus) or not set(gpus)<=set(range(7)):raise ValueError('only_gpu0_to6_allowed')
    pointer=BASE/'qwen-deploy'/a.pointer
    with pointer.with_suffix('.launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        old=read(pointer)
        if old and same_process(old['coordinator']):print(json.dumps(dict(old, status='already_running')));return
        if old and not a.resume:print(json.dumps({'status':'existing_result_use_resume','pointer':str(pointer)}));return
        if old:
            record=old;out=Path(old['pipeline'])
            if read(Path(record['result'])/'report.json',{}).get('status')=='completed':
                print(json.dumps({'status':'already_completed'}));return
        else:
            stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            out=BASE/'results'/(a.name+'-'+stamp);out.mkdir()
            record=dict(code=str(ROOT),pipeline=str(out),result=str(out/'experiment'),gpus=list(gpus),after=a.after,pilot=a.pilot)
        # Freeze all source and configuration bytes. Resume must use the same files.
        import hashlib
        manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in list(ROOT.glob('*.py'))+list((ROOT/'configs').glob('*.json'))}
        prior=read(out/'code-manifest.json')
        if prior is not None and prior!=manifest:raise RuntimeError('frozen_source_changed')
        dump(out/'code-manifest.json',manifest)
        logpath=out/('queue-'+str(__import__('time').time_ns())+'.log')
        with (out/'pipeline.lock').open('a') as lease,logpath.open('xb') as log:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            child=subprocess.Popen([AGENT_PYTHON,str(ROOT/a.script),'--output',record['result'],'--after',record['after'],'--gpus',','.join(map(str,record['gpus'])),'--pilot',record['pilot']],
                cwd=ROOT,env=env(0),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,pass_fds=(lease.fileno(),))
            record.update(status='started',coordinator=identity(child.pid));dump(pointer,record);dump(out/'launch.json',record)
        print(json.dumps(record))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--after',required=True);p.add_argument('--pointer',default='latest-memrsi-stream-v1_6.json')
    p.add_argument('--gpus',default='0,1,2');p.add_argument('--pilot',required=True);p.add_argument('--script',default='trajectory_pipeline.py');p.add_argument('--name',default='memrsi-stream-v1_6');p.add_argument('--resume',action='store_true')
    main(p.parse_args())
