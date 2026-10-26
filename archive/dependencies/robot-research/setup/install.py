"""Isolated environment installation, resumable steps; never edits existing PAOS envs."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path('/data/stormlab/xi/robot')

def record(path,data):
    p=Path(path);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));tmp.replace(p)

def main(name):
    os.umask(0o077)
    prefix=ROOT/'envs'/name
    env=dict(os.environ,PATH=str(prefix/'bin')+':'+os.environ['PATH'],
        PIP_CACHE_DIR=str(ROOT/'cache/pip'),TMPDIR=str(ROOT/'cache'),
        HF_HOME=str(ROOT/'cache/huggingface'),HF_HUB_DISABLE_TELEMETRY='1',
        CUDA_VISIBLE_DEVICES='',PIP_DISABLE_PIP_VERSION_CHECK='1',
        MAX_JOBS='2',CMAKE_BUILD_PARALLEL_LEVEL='2',OMP_NUM_THREADS='2',
        OPENBLAS_NUM_THREADS='2',TORCH_CUDA_ARCH_LIST='8.0',
        CUDA_HOME=str(prefix),PYNPUT_BACKEND='dummy',MUJOCO_GL='egl')
    state=ROOT/'setup'/f'install-{name}.json'
    create=json.loads((ROOT/'setup'/f'create-{name}.json').read_text())
    while True:
        try:
            raw=Path(f"/proc/{create['pid']}/stat").read_text().rsplit(')',1)[1].split()
            alive=raw[0]!='Z' and raw[19]==create['start_ticks']
        except FileNotFoundError:alive=False
        if not alive:break
        record(state,{'phase':'waiting_environment','pid':os.getpid()});time.sleep(5)
    py=prefix/'bin/python'
    if not py.exists():raise RuntimeError('environment_creation_failed')
    def run(tag,cmd,cwd=None):
        marker=ROOT/'setup'/f'{name}-{tag}.done.json'
        if marker.exists():return
        record(state,{'phase':tag,'pid':os.getpid(),'updated':time.time()})
        log=ROOT/'logs'/f'{name}-{tag}.log'
        with log.open('a') as f:
            completed=subprocess.run([str(x) for x in cmd],cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f)
        if completed.returncode:
            record(state,{'phase':'failed','step':tag,'exit_code':completed.returncode,'log':str(log)})
            raise RuntimeError('install_step_failed')
        record(marker,{'status':'completed','time':time.time()})
    pip=[py,'-m','pip']
    run('packaging',pip+['install','--upgrade','pip','wheel','setuptools==69.5.1','setproctitle','packaging','ninja'])
    if name=='casa':
        run('packages',pip+['install','-e',ROOT/'src/robosuite','-e',ROOT/'src/robocasa'])
    else:
        run('torch',pip+['install','torch==2.4.1','torchvision==0.19.1','--index-url','https://download.pytorch.org/whl/cu121'])
        run('packages',pip+['install','-r',ROOT/'src/RoboTwin/scripts/requirements.txt'])
        run('xpolicylab',pip+['install','-e',ROOT/'src/RoboTwin/XPolicyLab'])
        curobo=ROOT/'src/RoboTwin/envs/curobo'
        if not curobo.exists():run('curobo-clone',['git','clone','--depth','1','--branch','v0.7.8','https://github.com/NVlabs/curobo.git',curobo])
        run('curobo',pip+['install','-e',curobo,'--no-build-isolation'])
        run('warp',pip+['install','warp-lang==1.12.0','setuptools==69.5.1'])
    run('pip-check',pip+['check'])
    exe=prefix/'bin/robot'
    if not exe.exists():shutil.copy2(py.resolve(),exe)
    record(state,{'phase':'packages_installed','pid':os.getpid(),'updated':time.time(),
                  'render_validation_pending':True,'executable':str(exe)})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('name',choices=['twin','casa']);a=p.parse_args()
    main(a.name)
