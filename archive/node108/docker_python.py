#!/usr/bin/python3
import os,sys
from pathlib import Path
b=Path('/data/songziying/paos-libero-20261023')
policy='paos-policy' in sys.argv[0]
image='phyagentos-openpi-hcu:pi05-v016-dtk2604-20260901' if policy else 'sha256:3171fda2362d773433482f79c4fd53f6f428413efbf41c3fdfb43d8c799d6c95'
name='songziying-paos-'+('policy' if policy else 'physics')+'-'+str(os.getpid())
args=['docker','run','--rm','-i','--name',name,'--label','paos.owner=songziying-libero-20261023','--network','host','--cpus','4','--memory','64g' if policy else '6g','--shm-size','2g','-v',f'{b}:{b}','-v','/data/fba-closedloop-week-deps:/data/fba-closedloop-week-deps:ro']
for k in ('PYTHONPATH','LIBERO_CONFIG_PATH','PAOS_LANE_GPU','PAOS_LIBERO_SOURCE','PAOS_CORE_ROOT','PAOS_MIGRATION_ROOT','PAOS_POLICY_CHECKPOINT','MUJOCO_GL','PYOPENGL_PLATFORM','MUJOCO_EGL_DEVICE_ID','LIBGL_ALWAYS_SOFTWARE'):
 if k in os.environ:
  args+=['-e',f'PYTHONPATH={b}/physics-vendor:'+os.environ[k]] if k=='PYTHONPATH' and not policy else ['-e',k]
args+=['-e','OMP_NUM_THREADS=4','-e','OPENBLAS_NUM_THREADS=4','-e','MKL_NUM_THREADS=4','-e','PYTHONUNBUFFERED=1','-e','PYTHONDONTWRITEBYTECODE=1']
if policy:
 gpu=int(os.environ.get('PAOS_LANE_GPU','7'))
 args+=['--device','/dev/kfd','--device',f'/dev/dri/renderD{128+gpu}','-v','/opt/hyhal:/opt/hyhal:ro','-e','HIP_VISIBLE_DEVICES=0','-e','ROCR_VISIBLE_DEVICES=0','-e','JAX_PLATFORMS=cpu','-e','USE_TF=0','-e','USE_FLAX=0','-e',f'XDG_CACHE_HOME={b}/cache','-e',f'OPENPI_DATA_HOME={b}/cache/openpi','--entrypoint','/bin/bash',image,'-lc','source /opt/dtk/env.sh; source /opt/hyhal/env.sh; exec python "$@"','paos',*sys.argv[1:]]
else:
 args+=['--entrypoint','/usr/local/bin/python3',image,*sys.argv[1:]]
os.execvp('docker',args)
