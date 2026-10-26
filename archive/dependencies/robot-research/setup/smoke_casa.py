"""Native kitchen environment reset / observation / simulation-step test, not a policy evaluation."""
import json,os,time
from pathlib import Path
import numpy as np
import imageio.v2 as imageio
from robocasa.utils.env_utils import create_env
root=Path('/data/stormlab/xi/robot');out=root/'runs/casa-smoke';out.mkdir(parents=True,exist_ok=True)
env=create_env('PickPlaceCounterToCabinet',seed=0,layout_ids=[1],style_ids=[1],
 camera_names=['robot0_agentview_left'],camera_widths=128,camera_heights=128,
 render_gpu_device_id=0)
obs=env.reset();frames=[]
for _ in range(8):
 obs,reward,done,info=env.step(np.zeros(env.action_dim))
 frames.append(obs['robot0_agentview_left_image'][::-1])
assert frames[-1].shape==(128,128,3)
assert np.isfinite(frames[-1]).all() and frames[-1].std()>0
imageio.imwrite(out/'scene.png',frames[-1])
imageio.mimsave(out/'smoke.mp4',frames,fps=10)
result={'status':'passed','task':'PickPlaceCounterToCabinet','seed':0,'steps':8,
 'action_dim':env.action_dim,'frame_shape':list(frames[-1].shape),'gpu':os.environ.get('ROBOT_GPU'),
 'scope':'environment reset, camera rendering, and action stepping only; not grasp success or MemRSI evaluation', 'time':time.time()}
env.close();(out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
