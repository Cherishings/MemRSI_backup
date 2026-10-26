"""New seed, 32+8 actual steps, history-preserving language change; no task score."""
import argparse,json,time,traceback
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    env=None;writer=None;steps=0
    try:
        import setproctitle;setproctitle.setproctitle('robot')
        import numpy as np,imageio.v2 as imageio
        from environment import load_controller,load_scene
        from history_controller import history_digest
        from audit import seed_all,code_hashes
        seeds=seed_all(11)
        c=load_controller();env,obs,initial,_=load_scene(c,11);c.instruct(initial)
        writer=imageio.get_writer(a.output/'segment.mp4',fps=20)
        for _ in range(32):
            writer.append_data(np.concatenate([obs['robot0_agentview_center_image'][::-1],obs['robot0_eye_in_hand_image'][::-1]],axis=1))
            obs,_,_,_=env.step(c.act(obs));steps+=1
        m=c.executor.model.model;before=history_digest(m);old_calls=m.action_calls
        text='Wash the fruit and then leave it in the sink.'
        update=c.instruct(text);after=history_digest(m)
        captures=[]
        def hook(module,inputs):captures.append(inputs[0].detach().float().cpu().numpy().copy())
        handle=m.prism_language_embedding_encoder.register_forward_pre_hook(hook)
        try:
            for _ in range(8):
                writer.append_data(np.concatenate([obs['robot0_agentview_center_image'][::-1],obs['robot0_eye_in_hand_image'][::-1]],axis=1))
                obs,_,_,_=env.step(c.act(obs));steps+=1
        finally:handle.remove()
        expected=c.embedding_cache[text];error=float(np.max(np.abs(captures[0].reshape(-1,512)[0]-expected))) if captures else None
        result=dict(status='pass' if before==after and error is not None and error<1e-6 and m.action_calls==40 else 'failed',seed=11,actual_environment_steps=steps,history_digest_before=before,history_digest_after=after,history_preserved=before==after,action_calls_before=old_calls,action_calls_after=m.action_calls,language_mlp_calls_after_change=len(captures),new_embedding_error=error,update=update,policy_forwards_or_actions=40,task_success_claim=False,learning_calls=0,high_level_LLM_calls=0,scope='real short execution validates history-preserving language change; not full task or MemRSI benefit')
    except Exception as e:
        result=dict(status='technical_failure',error_type=type(e).__name__,error_message=str(e)[:200],actual_environment_steps=steps)
        (a.output/'exception.private.txt').write_text(traceback.format_exc())
    finally:
        if writer:writer.close()
        if env:env.close()
    result['time']=time.time();result['source_hashes']=code_hashes();result['execution_seeds']=seeds;(a.output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return 0 if result['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(main())
