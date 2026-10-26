"""Simulator adapters. Privileged evaluator state is not passed to policy.act()."""
import importlib
import json
import os
from pathlib import Path
import sys
import numpy as np
from catalog import TASKS

ROOT=Path('/data/stormlab/xi/robot')

class PolicyProtocolError(ValueError):
    """An actor output is invalid, not an infrastructure outage."""
    pass

def checked_action(action,dim):
    try:a=np.asarray(action,dtype=float)
    except (ValueError,TypeError,OverflowError) as ex:raise PolicyProtocolError('non_numeric_action') from ex
    if a.shape!=(dim,) or not np.isfinite(a).all():raise PolicyProtocolError('invalid_action')
    return a

def public_casa(obs):
    # Exclude object-state, task-id, source-container and simulator metadata.
    return {k:v for k,v in obs.items() if k.endswith('_image') or
            (k.startswith('robot0_') and any(x in k for x in
              ('joint_pos','joint_vel','eef_pos','eef_quat','gripper_qpos','gripper_qvel','base_pos','base_quat')))}

def public_twin(obs):
    return {'images':{k:v['rgb'] for k,v in obs['observation'].items() if 'rgb' in v},
            'joint_action':obs['joint_action'], 'endpose':obs['endpose']}

class RMBench:
    def __init__(self,task,seed,out):
        if task not in TASKS['rmbench']:raise ValueError('unknown_task')
        import yaml
        repo=ROOT/'src/RMBench';os.chdir(repo);sys.path.insert(0,str(repo))
        config=repo/'env_cfg/task_config'
        args=yaml.safe_load((config/'demo_clean.yml').read_text())
        camera=yaml.safe_load((config/'_camera_config.yml').read_text())[args['camera']['head_camera_type']]
        args.update(head_camera_h=camera['h'],head_camera_w=camera['w'],eval_video_log=False)
        robot=repo/'assets/embodiments/aloha-agilex'
        args.update(task_name=task,task_config='demo_clean',left_robot_file=str(robot),
            right_robot_file=str(robot),dual_arm_embodied=True,embodiment_name='aloha-agilex',
            left_embodiment_config=yaml.safe_load((robot/'config.yml').read_text()),
            right_embodiment_config=yaml.safe_load((robot/'config.yml').read_text()),
            collect_data=False,render_freq=0,need_plan=False,eval_mode=True,save_path=str(out))
        cls=getattr(importlib.import_module('envs.'+task),task)
        self.env=cls();self.env.setup_demo(now_ep_num=0,seed=seed,**args)
        instruction=json.loads((repo/'description/task_instruction'/f'{task}.json').read_text())['seen'][0]
        if '{' in instruction:raise ValueError('unresolved_instruction_template')
        self.instruction=instruction;self.env.set_instruction(instruction)
        self.horizon=int(self.env.step_lim);self.steps=0
        self.obs=public_twin(self.env.get_obs())
        self.action_dim=len(self.obs['joint_action']['vector'])
        self.success=False
    def observe(self):return self.obs
    def hold_action(self):return np.asarray(self.obs['joint_action']['vector'])
    def step(self,action):
        a=checked_action(action,self.action_dim)
        self.env.take_action(a,action_type='qpos');self.steps+=1
        self.obs=public_twin(self.env.get_obs());self.success=bool(self.env.eval_success)
        return self.obs,self.success,self.success or self.steps>=self.horizon
    def frames(self):
        images=self.obs['images']
        return [images[k] for k in sorted(images,key=lambda k:('head' not in k,k))]
    def close(self):self.env.close_env()

class ReMemBench:
    def __init__(self,task,seed,out):
        if task not in TASKS['remembench']:raise ValueError('unknown_task')
        from robocasa.utils.env_utils import create_env
        import robocasa.environments.kitchen.memory
        self.env=create_env(task,seed=seed,layout_ids=[0],style_ids=[0],
            camera_names=['robot0_agentview_left','robot0_agentview_right','robot0_eye_in_hand'],
            camera_widths=128,camera_heights=128)
        self.obs=public_casa(self.env.reset());self.instruction=self.env.get_ep_meta()['lang']
        if not self.instruction or self.instruction=='There is no language here.':
            raise ValueError('upstream_instruction_missing')
        self.action_dim=self.env.action_dim;self.horizon=self.env.horizon;self.steps=0;self.success=False
    def observe(self):return self.obs
    def hold_action(self):return np.zeros(self.action_dim)
    def step(self,action):
        a=checked_action(action,self.action_dim)
        lo,hi=self.env.action_spec
        if np.any(a<lo) or np.any(a>hi):raise PolicyProtocolError('action_out_of_bounds')
        obs,_,done,_=self.env.step(a);self.steps+=1;self.obs=public_casa(obs)
        self.success=bool(self.env._check_success())
        return self.obs,self.success,bool(done or self.success or self.steps>=self.horizon)
    def frames(self):return [v[::-1] for k,v in self.obs.items() if k.endswith('_image')]
    def close(self):self.env.close()

def create(benchmark,task,seed,out):
    return {'rmbench':RMBench,'remembench':ReMemBench}[benchmark](task,seed,out)
