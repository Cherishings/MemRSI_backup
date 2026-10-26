"""Native action evaluation / bounded environment smoke; no hidden target to actor."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import traceback
import numpy as np
import imageio.v2 as imageio
from adapters import create,PolicyProtocolError
from catalog import COMMITS

def main():
    p=argparse.ArgumentParser();p.add_argument('benchmark');p.add_argument('task')
    p.add_argument('--seed',type=int,default=0);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['smoke','policy'],default='smoke')
    p.add_argument('--policy',type=Path);p.add_argument('--steps',type=int,default=8)
    a=p.parse_args()
    if a.mode=='policy' and (not a.policy or not a.policy.is_file()):p.error('policy Python file required')
    if a.mode=='smoke' and not 1<=a.steps<=8:p.error('smoke limited to 1..8 steps')
    a.output.mkdir(parents=True,exist_ok=False)
    result=dict(benchmark=a.benchmark,task=a.task,seed=a.seed,mode=a.mode,commits=COMMITS,
        status='running',started=time.time(),gpu=os.environ.get('ROBOT_GPU'),
        session_switches=0,scope='environment integration check' if a.mode=='smoke' else 'native-action rollout; policy identity recorded',
        success=None,agent_experiment=a.mode=='policy')
    env=None;video=None;actions=[]
    try:
        env=create(a.benchmark,a.task,a.seed,a.output)
        obs=env.observe(); frames=env.frames()
        if not frames or not any(float(f.std())>0 for f in frames):raise ValueError('empty_camera')
        imageio.imwrite(a.output/'scene.png',frames[0])
        for i,frame in enumerate(frames):imageio.imwrite(a.output/f'camera-{i}.png',frame)
        video=imageio.get_writer(a.output/'episode.mp4',fps=20)
        result.update(action_dim=env.action_dim,horizon=env.horizon,instruction=env.instruction)
        actor=None
        if a.mode=='policy':
            spec=importlib.util.spec_from_file_location('evaluated_policy',a.policy)
            actor=importlib.util.module_from_spec(spec);spec.loader.exec_module(actor)
            result['policy_sha256']=hashlib.sha256(a.policy.read_bytes()).hexdigest()
            # No task identifier, simulator object, target, or reward exposed to actor.
            actor.reset(instruction=env.instruction,action_dim=env.action_dim)
        limit=a.steps if a.mode=='smoke' else env.horizon
        for t in range(limit):
            action=env.hold_action() if actor is None else actor.act(obs)
            obs,success,done=env.step(action);actions.append(np.asarray(action))
            video.append_data(env.frames()[0])
            if done:break
        result.update(status='passed' if a.mode=='smoke' else ('success' if env.success else 'task_failure'),
            steps=env.steps,success=None if a.mode=='smoke' else env.success,
            evaluator_success_observed=env.success)
        np.savez_compressed(a.output/'actions.npz',actions=np.asarray(actions))
    except Exception as ex:
        result.update(status='protocol_failure' if isinstance(ex,PolicyProtocolError) else 'infrastructure_failure',
                      error_type=type(ex).__name__,error=str(ex)[:500])
        (a.output/'traceback.txt').write_text(traceback.format_exc())
    finally:
        for resource in (video,env):
            if resource:
                try:resource.close()
                except Exception as ex:
                    result.setdefault('cleanup_errors',[]).append(type(ex).__name__)
        result['finished']=time.time();(a.output/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    return 1 if result['status'] in ('infrastructure_failure','protocol_failure') else 0

if __name__=='__main__':raise SystemExit(main())
