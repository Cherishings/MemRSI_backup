"""Same visual inputs, budgets, execution chunks for native and frozen MemRSI."""
import argparse,asyncio,hashlib,json,time
from pathlib import Path

async def run(a):
    import setproctitle;setproctitle.setproctitle('robot')
    from adapted_action_contract import FixedTaskVisualAgent as VisualAgent
    from rpc_client import post,cameras,ActorInstructionError
    from runtime_config import usage_totals
    from model_provider import CALL_LIMIT
    p=json.loads((Path(__file__).parent/'protocol.json').read_text())
    assert CALL_LIMIT==p['high_level_logical_call_limit']
    actor=VisualAgent(a.arm,a.output/'actor',None if a.arm=='native' else a.policy,{'persistent_tokens':p['persistent_tokens'],'active_input_tokens':p['active_input_units'],'output_tokens_per_call':p['output_tokens']})
    result=dict(preflight=a.entry_smoke,attempt=a.attempt,arm=a.arm,seed=a.seed,status='running',reached_decisions=0,answered_decisions=0,steps=0,learning_calls=0,goal_repeated=False,expected_rollovers=p['conversation_rollover_after_decisions'],completed_rollovers=0)
    try:
        public=post(a.port,'observe',{})['public'];initial=public['instruction'];actor.bind_public_goal(initial)
        for index in range(1 if a.entry_smoke else p['max_decisions']):
            if public['steps']>=public['horizon']:break
            if index in p['conversation_rollover_after_decisions']:
                await actor.rollover();result['completed_rollovers']+=1
            request=('Requested outcome: '+initial if index==0 else p['resume_prompt'])+' Choose execute to continue the original full task under the fixed PRISM condition, or finish. The controller runs up to32 real steps and returns new observations. Judge actual progress and temporal obligations from observations and memory; a requested action is not evidence that it occurred.'
            result['reached_decisions']+=1
            choice=await actor.choose(request,cameras(public),public['proprio']);result['answered_decisions']+=1
            with (a.output/'decisions.jsonl').open('a') as f:f.write(json.dumps(dict(index=index,physical_steps=public['steps'],choice=choice))+'\n')
            if choice['skill']=='finish':result['stop_reason']='actor_finish';break
            response=post(a.port,'chunk',{'instruction':choice['instruction']});public=response['public'];await actor.observe(response['receipt']);result['steps']=public['steps']
            (a.output/'progress.json').write_text(json.dumps(dict(result,updated=time.time(),model_calls=actor.provider.calls),indent=2))
            if response['evaluator']['done']:result['stop_reason']='environment_terminal';break
        else:result['stop_reason']='decision_budget'
        post(a.port,'close',{'reason':result.get('stop_reason','physical_horizon')})
        score=json.loads((a.controller_output/'result.json').read_text());result.update(status=score['status'],official_check_success=score['official_check_success'],steps=score['steps'])
    except Exception as e:
        code=str(e)
        capacity={'active_context_budget_exceeded','persistent_memory_budget_exhausted','agent_call_budget_exhausted'}
        known={'native_session_archival_failed','action_protocol_failure','guidance_protocol_failure','guidance_review_protocol_failure','guidance_grounding_failure','invalid_guidance','generation_output_limit','delta_update_protocol_failure','delta_memory_schema'}
        result.update(status='paused_learning_budget' if code=='learning_budget_exhausted' else ('agent_failure' if isinstance(e,ActorInstructionError) or code in capacity|known else 'technical_failure'),error_type=type(e).__name__,error_code=code if code in capacity|known|{'learning_budget_exhausted'} or isinstance(e,ActorInstructionError) else 'interface_or_unclassified_failure')
        try:post(a.port,'close',{'reason':result['status']})
        except Exception:pass
    finally:
        result.update(model_logical_calls=actor.provider.calls,model_wire_attempts=actor.provider.wire_attempts,finished=time.time())
        result.update(usage_totals(a.output/'actor'))
        try:await actor.close()
        except Exception as e:result['cleanup_error']=type(e).__name__
        (a.output/'result.json').write_text(json.dumps(result,indent=2))
def main():
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=['native','memrsi'],required=True);p.add_argument('--seed',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--controller-output',type=Path,required=True);p.add_argument('--policy',type=Path,required=True);p.add_argument('--port',type=int,default=19253);p.add_argument('--entry-smoke',action='store_true');p.add_argument('--attempt',type=int,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);asyncio.run(run(a))
if __name__=='__main__':main()
