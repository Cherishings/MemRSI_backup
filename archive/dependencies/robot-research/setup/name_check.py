import ctypes,os,json,time
from pathlib import Path
cuda=ctypes.CDLL('libcuda.so.1');assert cuda.cuInit(0)==0
n=ctypes.c_int();assert cuda.cuDeviceGet(ctypes.byref(n),0)==0
ctx=ctypes.c_void_p();assert cuda.cuCtxCreate_v2(ctypes.byref(ctx),0,n)==0
Path('/data/stormlab/xi/robot/setup/name-check-live.json').write_text(json.dumps({'pid':os.getpid(),'gpu':os.environ.get('CUDA_VISIBLE_DEVICES')}))
time.sleep(25)
cuda.cuCtxDestroy_v2(ctx)
