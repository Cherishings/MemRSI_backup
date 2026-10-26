"""Shared process and environment helpers for physical feasibility tests."""
import argparse,concurrent.futures,fcntl,hashlib,json,os,signal,socket,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BASE=Path('/data/songziying/paos-libero-20261023/migration/portable-runtime-20261023/paos')
def dump(p,d):
    p=Path(p);t=p.with_suffix('.tmp');t.write_text(json.dumps(d,indent=2));t.replace(p)
def identity(pid):
    return {'pid':pid,'start_ticks':Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()[19]}
def ready(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):return True
    except OSError:return False
def env(g):
    return dict(os.environ,CUDA_VISIBLE_DEVICES=str(g),MUJOCO_EGL_DEVICE_ID=str(g),MUJOCO_GL='egl',PYOPENGL_PLATFORM='egl',
        LIBERO_CONFIG_PATH=str(BASE/'config/libero'),XLA_PYTHON_CLIENT_PREALLOCATE='false',OMP_NUM_THREADS='4',
        OPENBLAS_NUM_THREADS='4',MKL_NUM_THREADS='4',PYTHONUNBUFFERED='1',LITELLM_LOCAL_MODEL_COST_MAP='True',
        PYTHONPATH=str(ROOT)+':/data/stormlab/xi/openpi:/data/stormlab/xi/openpi/third_party/libero')
def stop_group(p):
    try:os.killpg(p.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:p.wait(25)
    except subprocess.TimeoutExpired:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.wait()
