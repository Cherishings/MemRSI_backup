"""Launch isolated benchmarks on GPU 0/1/2; reserve normal experiment GPUs by lease."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from catalog import TASKS

ROOT=Path('/data/stormlab/xi/robot');BASE=ROOT/'memory-bench'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('benchmark',choices=TASKS);p.add_argument('--task')
    p.add_argument('--list',action='store_true');p.add_argument('--gpu',type=int,choices=[0,1,2])
    p.add_argument('--seed',type=int,default=0);p.add_argument('--mode',choices=['smoke','policy'],default='smoke')
    p.add_argument('--policy',type=Path);p.add_argument('--wait',action='store_true')
    p.add_argument('--shared-smoke',action='store_true',help='Only an eight-step setup check; serial, no model inference')
    a=p.parse_args()
    if a.list:print('\n'.join(TASKS[a.benchmark]));return 0
    if a.task not in TASKS[a.benchmark] or a.gpu is None:p.error('known --task and --gpu required')
    if a.shared_smoke and a.mode!='smoke':p.error('shared access is limited to setup checks')
    if a.mode=='policy' and (a.policy is None or not a.policy.is_file()):p.error('--policy existing Python file required')
    for tag in ['install','assets']:
        s=BASE/(a.benchmark+'-'+tag+'.json')
        if not s.exists() or json.loads(s.read_text()).get('phase') not in ['ready','installed']:
            p.error('benchmark '+tag+' not ready; see '+str(s))
    os.umask(0o077)
    lock=BASE/'shared-smoke.lock' if a.shared_smoke else Path('/data/stormlab/xi/paos/qwen-deploy')/(
        'robot-run.lock' if a.gpu==0 else f'gpt-gpu{a.gpu}-run.lock')
    with lock.open('a') as lease:
        while True:
            try:
                fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
                used,total=map(int,subprocess.check_output(['nvidia-smi','-i',str(a.gpu),
                    '--query-gpu=memory.used,memory.total','--format=csv,noheader,nounits'],text=True).strip().split(','))
                if (a.shared_smoke and total-used>=4096) or (not a.shared_smoke and used<=1024):break
                fcntl.flock(lease,fcntl.LOCK_UN)
            except BlockingIOError:pass
            if not a.wait:print('GPU busy; no benchmark started.');return 3
            time.sleep(10)
        out=ROOT/'runs'/('memory-'+a.benchmark+'-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
        out.mkdir();prefix=ROOT/'envs'/a.benchmark
        env=dict(os.environ,CUDA_VISIBLE_DEVICES=str(a.gpu),ROBOT_GPU=str(a.gpu),
            MUJOCO_GL='egl',PYNPUT_BACKEND='dummy',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',
            PATH=str(prefix/'bin')+':'+os.environ['PATH'],
            LD_LIBRARY_PATH=str(ROOT/'envs/twin/lib')+':'+os.environ.get('LD_LIBRARY_PATH',''),
            CUDA_HOME=str(ROOT/'envs/twin'))
        command=[str(prefix/'bin/robot'),str(ROOT/'setup/bootstrap.py'),str(BASE/'episode.py'),
                 a.benchmark,a.task,'--seed',str(a.seed),'--mode',a.mode,'--output',str(out/'episode')]
        if a.policy:command+=['--policy',str(a.policy.resolve())]
        (out/'launch.json').write_text(json.dumps(dict(benchmark=a.benchmark,task=a.task,gpu=a.gpu,
            seed=a.seed,mode=a.mode,shared_smoke=a.shared_smoke,command=command),indent=2))
        print(str(out),flush=True)
        with (out/'run.log').open('w') as log:
            child=subprocess.Popen(command,env=env,stdout=log,stderr=log,pass_fds=(lease.fileno(),))
            (out/'identity.json').write_text(json.dumps(dict(pid=child.pid,
                start_ticks=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()[19])))
            try:code=child.wait(timeout=180 if a.shared_smoke else None)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                code=124
        summary=dict(exit_code=code,output=str(out),finished=time.time())
        r=out/'episode/result.json'
        if r.exists():summary['result']=json.loads(r.read_text())
        (out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
        return code

if __name__=='__main__':raise SystemExit(main())
