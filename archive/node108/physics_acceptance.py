"""One real observation -> unchanged paired pi05 -> five simulator steps. Not a scored trial."""
import json,os,time
from pathlib import Path
import numpy as np
from libero.libero import benchmark,get_libero_path
from libero.libero.envs import OffScreenRenderEnv
from openpi_client import image_tools,websocket_client_policy
from paired_sampling import sampling_seed,BASE_SEED
B=Path(__file__).resolve().parent;out=B/'qualification';out.mkdir(exist_ok=True)
suite=benchmark.get_benchmark_dict()['libero_spatial']();task=suite.get_task(0)
env=OffScreenRenderEnv(bddl_file_name=str(Path(get_libero_path('bddl_files'))/task.problem_folder/task.bddl_file),
 camera_heights=256,camera_widths=256,render_gpu_device_id=0)
try:
 env.seed(0);env.reset();obs=env.set_init_state(suite.get_task_init_states(0)[0])
 for _ in range(10):obs,_,_,_=env.step([0,0,0,0,0,0,-1])
 q=np.array(obs['robot0_eef_quat']);q[3]=np.clip(q[3],-1,1);den=np.sqrt(1-q[3]*q[3]);axis=np.zeros(3) if den<1e-8 else q[:3]*2*np.arccos(q[3])/den
 seed=sampling_seed(BASE_SEED,'libero_spatial',0,0,1,0)
 req={'observation/image':image_tools.convert_to_uint8(image_tools.resize_with_pad(np.ascontiguousarray(obs['agentview_image'][::-1,::-1]),224,224)),
      'observation/wrist_image':image_tools.convert_to_uint8(image_tools.resize_with_pad(np.ascontiguousarray(obs['robot0_eye_in_hand_image'][::-1,::-1]),224,224)),
      'observation/state':np.concatenate((obs['robot0_eef_pos'],axis,obs['robot0_gripper_qpos'])),
      'prompt':task.language,'_paired_sampling_seed':seed}
 client=websocket_client_policy.WebsocketClientPolicy('127.0.0.1',20507)
 start=time.monotonic();response=client.infer(req);elapsed=time.monotonic()-start
 actions=np.asarray(response['actions']);assert actions.ndim==2 and actions.shape[1]==7 and np.isfinite(actions).all()
 assert response['paired_sampling']['seed']==seed
 for a in actions[:5]:obs,_,done,_=env.step(a.tolist())
 np.save(out/'actions.npy',actions[:5]);np.save(out/'last-frame.npy',obs['agentview_image'])
 result={'status':'passed','time':time.time(),'policy_calls':1,'model_action_steps':5,'initialization_steps':10,
  'inference_seconds':elapsed,'task':task.name,'paired_sampling':response['paired_sampling'],
  'scope':'Local deployment acceptance with one simulator; not G/U or RSI evidence and not proof of seven-scene memory capacity'}
 (out/'physical-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
finally:env.close()
