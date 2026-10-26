"""One genuine actor episode; evaluator outputs never enter the actor prompt."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time


async def run(args):
    import setproctitle
    setproctitle.setproctitle('robot')
    from rmb_visual_actor import RMBVisualAgent as VisualAgent
    from rpc_client import post, decode_cameras, predict, observe_step
    from failure_classification import classify
    from runtime_config import usage_totals
    args.output.mkdir(parents=True, exist_ok=True)
    policy = None if args.arm == 'native' else args.policy
    actor = VisualAgent(args.arm, args.output / 'actor', policy,
                        {'persistent_tokens': 1024, 'active_input_tokens': 12288,
                         'output_tokens_per_call': 2048})
    status = {'arm': args.arm, 'seed': args.seed, 'task': 'cover_blocks',
              'started': time.time(), 'status': 'running', 'scope': 'paired visual PAOS/MemRSI with shared frozen learned execution controller',
              'learning_enabled': False,
              'rule_updates_within_episode': False,
              'split': os.environ.get('MEMRSI_PHASE', 'test'),
              'learning_ledger_configured': bool(os.environ.get('MEMRSI_LEARNING_LEDGER')),
              'memory_policy_sha256': hashlib.sha256(args.policy.read_bytes()).hexdigest() if policy else None,
              'execution_continuity': 'atomic_cover_v6_start_continue_replace',
              'chunk_steps': 8, 'semantic_max_steps': 32, 'decision_limit': 600, 'native_horizon_enforced': True}
    status.update(planned_decisions_max=600, reached_decisions=0, answered_decisions=0,
                  model_logical_call_limit=480, model_output_tokens_per_call=2048,
                  guidance_and_archive_calls_count_toward_same_limit=True,
                  instruction_visibility='full public task goal repeated at every actor decision',
                  memory_scope='official historical visual task; not a cross-session mission trial')
    phase = 'controller'
    try:
        post(args.controller_port, 'reset', {'episode_seed': args.seed})
        public = post(args.simulator_port, 'observe', {})['public']
        status.update(planned_physical_steps_max=public['horizon'],
                      # A learned boundary can occur after the very first real
                      # step, so ceil(horizon/8) is not a valid upper bound.
                      planned_decisions_max=min(600, public['horizon']))
        decisions = 0
        previous_instruction = None
        physical_rpc_chunks = 0
        while public['steps'] < public['horizon'] and decisions < 600:
            phase = 'actor'
            status['reached_decisions'] += 1
            decision = await actor.choose(
                'Requested outcome: ' + public['instruction'] +
                '\nChoose ONE atomic cover manipulation, continue the committed manipulation, or finish. The controller will continue it until a predicted subtask boundary or at most 32 physical steps before the next observation. A subgoal can span multiple segments. '
                'Use the current cameras and remembered execution feedback; do not assume an instruction succeeded.',
                cameras=decode_cameras(public), proprio=public['proprio'])
            decisions += 1
            status['answered_decisions'] = decisions
            with (args.output / 'decisions.jsonl').open('a') as handle:
                handle.write(json.dumps({'decision': decisions, 'step': public['steps'], 'action': decision}) + '\n')
            if decision['skill'] == 'finish':
                status['stop_reason'] = 'actor_finish'
                break
            segment_start = public['steps']
            continuity = decision.get('continuity')
            if continuity not in ('start', 'continue', 'replace'):
                raise RuntimeError('action_protocol_failure')
            semantic_changed = continuity == 'replace'
            if continuity == 'continue' and decision['instruction'] != previous_instruction:
                raise RuntimeError('committed_instruction_mismatch')
            segment_done = False
            learned_boundary = False
            while public['steps'] < min(public['horizon'], segment_start + 32):
                phase = 'controller'
                predicted = predict(args.controller_port, public, decision['instruction'], new_subtask=semantic_changed)
                semantic_changed = False
                for action in predicted['actions']:
                    before = public['steps']
                    phase = 'simulator'
                    response = post(args.simulator_port, 'step', {'actions': [action]})
                    public = response['public']
                    if public['steps'] != before + 1:
                        raise RuntimeError('physical_step_accounting_mismatch')
                    physical_rpc_chunks += 1
                    phase = 'controller'
                    execution_receipt = observe_step(args.controller_port, public)
                    learned_boundary = execution_receipt['boundary_ready']
                    segment_done = bool(response['evaluator']['done'])
                    if segment_done or learned_boundary or public['steps'] >= public['horizon']:
                        break
                if segment_done or learned_boundary:
                    break
            previous_instruction = decision['instruction']
            phase = 'actor_receipt'
            await actor.observe('Executed ' + str(public['steps'] - segment_start) +
                ' real control steps under the committed instruction. Controller predicts subtask boundary: ' +
                str(learned_boundary) + '. This prediction is not verified task completion. Inspect current observations.')
            status.update(physical_rpc_chunks=physical_rpc_chunks, lower_level_observation_updates=execution_receipt['observation_updates'],
                          semantic_resets=execution_receipt['semantic_resets'])
            status.update(decisions=decisions, steps=public['steps'], controller=predicted['controller'],
                          model_logical_calls=actor.provider.calls, updated=time.time())
            (args.output / 'progress.json').write_text(json.dumps(status, indent=2))
            if segment_done:
                status['stop_reason'] = 'native_terminal'
                break
        else:
            status['stop_reason'] = 'native_horizon' if public['steps'] >= public['horizon'] else 'decision_budget'
        post(args.simulator_port, 'close', {})
        native_result = json.loads((args.simulator_output / 'result.json').read_text())
        status.update(status=native_result['status'], official_check_success=native_result['official_check_success'],
                      steps=native_result['steps'], decisions=decisions)
    except Exception as error:
        if str(error) == 'learning_budget_exhausted':
            failure_status, error_code = 'paused_learning_budget', 'learning_budget_exhausted'
        else:
            failure_status, error_code = classify(error, phase)
        status.update(status=failure_status, error_type=type(error).__name__, error_code=error_code, failure_phase=phase)
        try:
            post(args.simulator_port, 'close', {})
        except Exception:
            pass
    finally:
        status.update(model_logical_calls=actor.provider.calls,
                      model_wire_attempts=actor.provider.wire_attempts,
                      model_transport_retries=actor.provider.transport_retries)
        status.update(usage_totals(args.output / 'actor'))
        try:
            await actor.close()
        except Exception as error:
            status['cleanup_error'] = type(error).__name__
        status['finished'] = time.time()
        (args.output / 'result.json').write_text(json.dumps(status, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=['native', 'memrsi'], required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--simulator-output', type=Path, required=True)
    parser.add_argument('--controller-port', type=int, default=19242)
    parser.add_argument('--simulator-port', type=int, default=19243)
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
