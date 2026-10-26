from pathlib import Path
import os
ROOT=Path(__file__).resolve().parent
ROBOT_ROOT=Path('/data/stormlab/xi/robot')
BASE=ROBOT_ROOT/'official-memory-remem-20261017'
R2=ROBOT_ROOT/'official-memory-remem-r2-language-20261017'
def execution_env(gpu=3):
    libs=list((BASE/'venv/lib/python3.10/site-packages/nvidia').glob('*/lib'))+list((ROBOT_ROOT/'envs/twin/lib/python3.10/site-packages/nvidia').glob('*/lib'))+[ROBOT_ROOT/'envs/twin/lib']
    return dict(os.environ,CUDA_VISIBLE_DEVICES=str(gpu),MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(gpu),OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',LD_LIBRARY_PATH=':'.join(map(str,libs)),PYTHONPATH=':'.join(map(str,[ROOT,BASE,R2,BASE/'PRISM',ROBOT_ROOT/'src/ReMemBench',ROBOT_ROOT/'src/robosuite-remem'])),HF_HUB_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
