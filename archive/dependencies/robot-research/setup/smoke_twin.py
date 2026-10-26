"""Native RoboTwin scene / robot / camera / stepping smoke test."""
import os,sys,json,time
from pathlib import Path
root=Path('/data/stormlab/xi/robot');repo=root/'src/RoboTwin';os.chdir(repo);sys.path.insert(0,str(repo))
import yaml,numpy as np
from envs.pick_dual_bottles import pick_dual_bottles
configs=repo/'env_cfg/task_config'
args=yaml.safe_load((configs/'demo_clean.yml').read_text())
emb=yaml.safe_load((configs/'_embodiment_config.yml').read_text())
robot_file=emb['aloha-agilex']['file_path']
args.update(task_name='pick_dual_bottles',task_config='demo_clean',left_robot_file=robot_file,
 right_robot_file=robot_file,dual_arm_embodied=True,embodiment_name='aloha-agilex',
 left_embodiment_config=yaml.safe_load((Path(robot_file)/'config.yml').read_text()),
 right_embodiment_config=yaml.safe_load((Path(robot_file)/'config.yml').read_text()),
 collect_data=False,render_freq=0,need_plan=False,save_path=str(root/'runs/twin-smoke'))
out=root/'runs/twin-smoke';out.mkdir(parents=True,exist_ok=True)
env=pick_dual_bottles();env.setup_demo(now_ep_num=0,seed=0,**args)
for _ in range(8):env.scene.step()
env.scene.update_render();obs=env.get_obs()
# The native observation dictionary must contain rendered image observations.
frames=[]
def find_images(x):
 if isinstance(x,dict):
  for v in x.values():find_images(v)
 elif isinstance(x,np.ndarray) and x.ndim==3 and x.shape[-1] in (3,4):frames.append(x)
find_images(obs)
assert frames and any(float(f.std())>0 for f in frames)
import imageio.v2 as imageio
f=next(f for f in frames if f.dtype==np.uint8) if any(f.dtype==np.uint8 for f in frames) else (np.clip(frames[0],0,1)*255).astype('uint8')
imageio.imwrite(out/'scene.png',f[:,:,:3])
result={'status':'passed','task':'pick_dual_bottles','seed':0,'steps':8,'image_count':len(frames),
 'gpu':os.environ.get('ROBOT_GPU'),'scope':'native scene, robot, rendering, and simulation stepping only; not expert or learned-policy success','time':time.time()}
(out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
