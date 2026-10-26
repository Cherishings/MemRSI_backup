from pathlib import Path
import shutil,json,os
b=Path('/data/songziying/paos-libero-20261023');r=b/'study';m=b/'migration'
for role in ('paos-policy','paos-libero-py38'):
 p=m/'conda-envs'/role/'bin/python';shutil.copy2(b/'docker_python.py',p);p.chmod(0o755)
p=r/'code/runtime/policy_entry.py';p.write_text('import runpy\nrunpy.run_path("'+str(b/'policy_hcu.py')+'",run_name="__main__")\n')
sh=(b/'env.sh');sh.write_text(f'''export PAOS_MIGRATION_ROOT={m}
export PAOS_LIBERO_SOURCE={r}/source
export PAOS_CORE_ROOT={r}/paos-core
export PAOS_GATEWAY_URL=http://127.0.0.1:19098/v1
export PAOS_LANE_GPU=7
export LIBERO_CONFIG_PATH={m}/runtime-config/libero
export PYTHONPATH={r}/code/runtime:{r}/code:{r}/source:{r}/paos-core:{m}/openpi/src:{m}/openpi/packages/openpi-client/src:{m}/openpi/third_party/libero
export MUJOCO_GL=egl PYOPENGL_PLATFORM=egl MUJOCO_EGL_DEVICE_ID=0 LIBGL_ALWAYS_SOFTWARE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
export PYTHONUNBUFFERED=1
export PATH={m}/conda-envs/paos-agent/bin:$PATH
''')
p=b/'physics_acceptance.py';p.write_text(p.read_text().replace("20500)","20507)"))
print('wrappers ready')
