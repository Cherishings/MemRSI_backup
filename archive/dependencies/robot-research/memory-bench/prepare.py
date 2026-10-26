"""Install benchmark overlays only. Never mutate the existing twin/casa environments."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/data/stormlab/xi/robot')
OUT = ROOT/'memory-bench'

def record(name, **data):
    p=OUT/(name+'.json'); tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(time=time.time(), **data), indent=2));tmp.replace(p)

def install(name):
    prefix=ROOT/'envs'/name
    env=dict(os.environ, CUDA_VISIBLE_DEVICES='', PYNPUT_BACKEND='dummy',
             PIP_CACHE_DIR=str(ROOT/'cache/pip'), PIP_DISABLE_PIP_VERSION_CHECK='1',
             OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    log=OUT/(name+'-install.log')
    def run(tag,cmd):
        record(name+'-install',phase=tag,pid=os.getpid())
        with log.open('a') as f:
            code=subprocess.call([str(x) for x in cmd], env=env,stdout=f,stderr=f)
        if code:raise RuntimeError(tag+'_exit_'+str(code))
    try:
        if not (prefix/'bin/python').exists():
            run('create_overlay',[ROOT/'envs/twin/bin/python','-m','venv','--system-site-packages',prefix])
        py=prefix/'bin/python'
        if name=='remembench':
            run('dependencies',[py,'-m','pip','install','numpy==1.23.3','numba==0.56.4',
                'mujoco==3.2.6','mink==0.0.5','pygame','pynput','hidapi','tianshou==0.4.10',
                'opencv-python==4.10.0.84','lxml','setproctitle','imageio-ffmpeg','pytest'])
            run('official_forks',[py,'-m','pip','install','--no-deps','-e',ROOT/'src/robosuite-remem',
                                 '-e',ROOT/'src/ReMemBench'])
        # RMBench uses the already verified, read-only twin dependencies.
        shutil.copy2((ROOT/'envs/twin/bin/python').resolve(),prefix/'bin/robot')
        run('package_inventory',[py,'-m','pip','freeze'])
        record(name+'-install',phase='installed',prefix=str(prefix),
               parent_read_only=str(ROOT/'envs/twin'),physics_tested=False)
    except Exception as e:
        record(name+'-install',phase='failed',error=str(e));raise

if __name__=='__main__':
    os.umask(0o077);OUT.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        list(pool.map(install,['rmbench','remembench']))
