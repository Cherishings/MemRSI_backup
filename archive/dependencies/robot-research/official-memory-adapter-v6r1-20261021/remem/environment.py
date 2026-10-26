"""Official environment initialization; task metadata never enters actor payload."""
import json,os
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent/'official-memory-remem-20261017'
CLIP=ROOT.parent/'official-memory-remem-r2-language-20261017/policy-assets'

def load_controller():
    import timm
    from history_controller import HistoryController
    os.chdir(BASE/'PRISM')
    create=timm.create_model
    def local(name,*args,**kwargs):
        if name=='vit_base_patch16_224.mae':kwargs['pretrained']=False
        return create(name,*args,**kwargs)
    timm.create_model=local
    try:return HistoryController(BASE/'policy-assets',CLIP)
    finally:timm.create_model=create

def load_scene(controller,seed):
    import h5py,robosuite,robocasa.environments.kitchen.memory
    from prism.util.casa_utils import make_env
    protocol=json.loads((ROOT/'protocol.json').read_text())
    with h5py.File(protocol['dataset'],'r') as f:
        ep=f['data'][sorted(f['data'])[0]];meta=json.loads(ep.attrs['ep_meta']);horizon=int(1.5*ep['actions'].shape[0])
    original=robosuite.make
    def public_make(*args,**kwargs):
        kwargs.update(seed=seed,camera_names=['robot0_agentview_center','robot0_eye_in_hand'],camera_heights=128,camera_widths=128)
        return original(*args,**kwargs)
    robosuite.make=public_make
    try:env,_=make_env(protocol['dataset'],controller.executor.keys_info,SimpleNamespace(controller='OSC_POSE',robots='PandaOmron',task_name=protocol['task'],render=False,control_freq=20))
    finally:robosuite.make=original
    env.set_ep_meta(meta);obs=env.reset()
    return env,obs,env.get_ep_meta()['lang'],min(horizon,protocol['chunk_steps']*protocol['max_decisions'])

def public_packet(obs,steps,horizon,instruction=None):
    import base64,numpy as np
    from live_policy import public_observation,IMAGE_KEYS
    safe=public_observation(obs)
    d=dict(steps=steps,horizon=horizon,cameras=[dict(shape=list(safe[k].shape),rgb_base64=base64.b64encode(np.ascontiguousarray(safe[k][::-1]).tobytes()).decode()) for k in IMAGE_KEYS],proprio={'gripper_qpos':safe['robot0_gripper_qpos'].tolist()})
    # Published robot joint cosine is not a joint position; do not relabel it.
    # The high-level actor receives gripper qpos and images; the shared PRISM
    # executor still receives the exact published cosine+gripper inputs.
    for source,target in [('robot0_joint_pos','joint_pos'),('robot0_eef_pos','eef_pos'),('robot0_eef_quat','eef_quat')]:
        if source in obs:d['proprio'][target]=np.asarray(obs[source]).tolist()
    if instruction is not None:d['instruction']=instruction
    return d
