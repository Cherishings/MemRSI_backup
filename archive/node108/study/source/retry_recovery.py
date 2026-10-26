"""Short physical release/lift between attempts; never resets object state."""
import numpy as np
from osc_handoff import read_pose,normalized_action,_limit_norm

def release_and_lift(controller,step_action,satisfied,max_steps=60):
    report={'steps':0,'goal_completed':False,'retreat_completed':False,'reset_environment':False,'lift_m':0.025}
    if satisfied():report['goal_completed']=True;return report
    pos,rot=read_pose(controller)
    neutral=normalized_action(controller,np.zeros(3),np.zeros(3))[:6]
    controller.set_goal(neutral,set_pos=pos.copy(),set_ori=rot.copy())
    target=pos.copy();target[2]+=0.025
    stable=0
    for i in range(max_steps):
        current,_=read_pose(controller)
        delta=np.zeros(3) if i<8 else _limit_norm(target-current,0.008)
        step_action(normalized_action(controller,delta,np.zeros(3)),'recovery_open' if i<8 else 'recovery_lift')
        report['steps']+=1
        # Stop immediately when the released object meets the task predicate.
        if satisfied():report['goal_completed']=True;break
        current,_=read_pose(controller)
        stable=stable+1 if i>=8 and np.linalg.norm(target-current)<=0.008 else 0
        if stable>=4:report['retreat_completed']=True;break
    return report

def release_and_verify(controller,step_action,satisfied,max_steps=30,required_stable=10):
    """Hold observed EEF pose and open; do not send more policy grasps after placement."""
    pos,rot=read_pose(controller)
    neutral=normalized_action(controller,np.zeros(3),np.zeros(3))[:6]
    controller.set_goal(neutral,set_pos=pos.copy(),set_ori=rot.copy())
    stable=0
    for i in range(max_steps):
        step_action(normalized_action(controller,np.zeros(3),np.zeros(3)),'placement_release_verify')
        stable=stable+1 if satisfied() else 0
        if stable>=required_stable:return {'success':True,'steps':i+1,'stable_steps':stable}
    return {'success':False,'steps':max_steps,'stable_steps':stable}
