import json,os,subprocess,time
from pathlib import Path
R=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-validation-20261023')
python='/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/conda-envs/paos-casa/bin/python'
code='''import mujoco,numpy as np,json
m=mujoco.MjModel.from_xml_string('<mujoco><worldbody><light pos="0 0 3"/><geom type="plane" size="2 2 .1" rgba=".4 .4 .4 1"/><body pos="0 0 .3"><joint type="free"/><geom type="box" size=".15 .15 .15" rgba="1 .2 .1 1" mass="1"/></body></worldbody></mujoco>')
d=mujoco.MjData(m)
for _ in range(10):mujoco.mj_step(m,d)
r=mujoco.Renderer(m,128,128);r.update_scene(d);f=r.render();assert np.isfinite(f).all() and f.std()>0
print(json.dumps({'passed':True,'pixel_std':float(f.std())}));r.close()
'''
rows=[]
for gpu in (2,3,4,6,7):
 used=int(subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
 if used>1024:rows.append({'gpu':gpu,'status':'busy_not_tested'});continue
 env=dict(os.environ,MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(gpu));env.pop('CUDA_VISIBLE_DEVICES',None)
 try:
  p=subprocess.run([python,'-c',code],env=env,capture_output=True,text=True,timeout=60)
  rows.append({'gpu':gpu,'exit_code':p.returncode,'result':json.loads(p.stdout) if p.returncode==0 else None,'error':p.stderr[-500:] if p.returncode else None})
 except Exception as e:rows.append({'gpu':gpu,'error_type':type(e).__name__})
(R/'gpu-render-acceptance.json').write_text(json.dumps({'time':time.time(),'rows':rows},indent=2));print(json.dumps(rows))
