"""Zero env-step audit: paired initialization and first action reproducibility."""
import argparse,gc,json,traceback
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    import setproctitle;setproctitle.setproctitle('robot')
    import numpy as np,torch
    from environment import load_controller,load_scene,public_packet
    from audit import code_hashes,seed_all,initial_evidence
    rows=[];env=None;c=None
    try:
        for seed in (17,17,29):
            seed_all(seed);c=load_controller();env,obs,text,horizon=load_scene(c,seed)
            evidence=initial_evidence(env,public_packet(obs,0,horizon,text),seed)
            c.instruct(text);action=c.act(obs)
            rows.append(dict(evidence=evidence,first_action=np.asarray(action).tolist(),actual_environment_steps=0))
            env.close();env=None;del c;c=None;gc.collect();torch.cuda.empty_cache()
        same_state=rows[0]['evidence']==rows[1]['evidence']
        error=float(np.max(np.abs(np.array(rows[0]['first_action'])-rows[1]['first_action'])))
        different_seed_state=rows[0]['evidence']['simulator_state_sha256']!=rows[2]['evidence']['simulator_state_sha256']
        different_seed_rgb=rows[0]['evidence']['public_rgb_sha256']!=rows[2]['evidence']['public_rgb_sha256']
        result=dict(status='pass' if same_state and error<=1e-7 and different_seed_state and different_seed_rgb else 'failed',paired_initial_state_exact=same_state,paired_first_action_max_abs_error=error,different_seeds_have_different_states=different_seed_state,different_seeds_have_different_rgb=different_seed_rgb,rows=rows,actual_environment_steps=0,policy_forwards=3,high_level_LLM_calls=0,learning_calls=0)
    except Exception as e:
        (a.output/'exception.private.txt').write_text(traceback.format_exc());result=dict(status='technical_failure',error_type=type(e).__name__,rows=rows,actual_environment_steps=0)
    finally:
        if env:env.close()
    result['source_hashes']=code_hashes();(a.output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('rows','source_hashes')}));return int(result['status']!='pass')
if __name__=='__main__':raise SystemExit(main())
