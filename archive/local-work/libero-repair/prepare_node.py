from pathlib import Path
import os,sys,subprocess,tarfile,json,shutil
b=Path('/data/songziying/paos-libero-20261023');r=b/'study';mig=b/'migration';deps=Path('/data/fba-closedloop-week-deps')
if not (r/'source').exists():
 with tarfile.open(b/'archives/frozen-study.tar') as t:t.extractall(r)
env=mig/'conda-envs/paos-agent';env.mkdir(parents=True,exist_ok=True)
if not (env/'bin/python').exists():
 with tarfile.open(b/'archives/paos-agent.tar.gz') as t:t.extractall(env)
 subprocess.run([str(env/'bin/python'),str(env/'bin/conda-unpack')],check=True)
(mig/'runtime-config/libero').mkdir(parents=True,exist_ok=True)
(mig/'models').mkdir(exist_ok=True)
for link,target in [(mig/'openpi',deps/'openpi'),(mig/'models/pi05_libero',deps/'checkpoints/pi05_libero_pytorch_fp32')]:
 if not link.exists():link.symlink_to(target,target_is_directory=True)
lib=deps/'openpi/third_party/libero/libero/libero'
(mig/'runtime-config/libero/config.yaml').write_text('\n'.join(f'{k}: {lib / v}' for k,v in {'benchmark_root':'.','bddl_files':'bddl_files','init_states':'init_files','datasets':'datasets','assets':'assets'}.items())+'\n')
old='/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022'
oldr='/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023-gpu67'
for path in list((r/'code').rglob('*.py'))+list((r/'source').glob('*.py')):
 s=path.read_text().replace(old,str(mig)).replace(oldr,str(r)).replace('http://127.0.0.1:19099','http://127.0.0.1:19098')
 path.write_text(s)
# Configure software EGL for physics only. Preserve all simulation/task semantics.
p=r/'code/runtime/libero_runtime.py';s=p.read_text().replace("checkpoint_params=self.checkpoint / 'params'","checkpoint_params=self.checkpoint / 'model.safetensors'")
s=s.replace("MUJOCO_EGL_DEVICE_ID=str(gpu)","MUJOCO_EGL_DEVICE_ID='0', LIBGL_ALWAYS_SOFTWARE='1'")
s=s.replace("kwargs['render_gpu_device_id'] = gpu", "kwargs['render_gpu_device_id'] = 0")
p.write_text(s)
site=env/'lib/python3.11/site-packages'
(site/'paos_deployment.pth').write_text(str(r/'paos-core')+'\n')
# Runtime credentials will be supplied separately with mode 600.
cred=mig/'portable-runtime-20261023/paos/qwen-deploy';cred.mkdir(parents=True,exist_ok=True)
# Fixed CPU tokenizer prevents network dependency at model load.
cache=b/'cache/openpi/openpi-assets';cache.mkdir(parents=True,exist_ok=True)
shutil.copy2(b/'archives/paligemma_tokenizer.model',cache/'paligemma_tokenizer.model')
for role in ('paos-policy','paos-libero-py38'):(mig/'conda-envs'/role/'bin').mkdir(parents=True,exist_ok=True)
print(json.dumps({'root':str(b),'python':subprocess.check_output([str(env/'bin/python'),'--version'],text=True).strip()}))
