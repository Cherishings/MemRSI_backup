"""Controlled history replay for operator experiments; never a physical success claim.

Replay actual public inputs and executed prefix actions. U is recomputed from
the start of the history (before all writes). At recovery the agent chooses.
Stop immediately on a divergent action; never feed another action's outcome.
"""
import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path


def dump(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False)); tmp.replace(p)


def fixture(source):
    source = Path(source)
    result = json.loads((source / 'result.json').read_text())
    events = [json.loads(s) for s in (source / 'received-events.jsonl').read_text().splitlines()]
    # A source protocol repair is not a second task decision. Reconstruct the
    # logical public history without its answer-free formatting retry message;
    # preserve the original file and explicitly report every omitted event.
    repair_text = 'Submit one report_action for the pending decision. No new task or correct answer is supplied.'
    repairs = [e['id'] for e in events if e['text'] == repair_text]
    if len(repairs) != len(result.get('format_repairs', [])):
        raise ValueError('source_protocol_repair_alignment_failure')
    events = [e for e in events if e['id'] not in repairs]
    from execution_contract import enrich_history
    events, receipt_ids = enrich_history(events, result['physical_executions'])
    decisions = result['decisions']
    requested = [e for e in events if e.get('decision_requested')]
    if len(requested) != len(decisions):
        raise ValueError('source_decision_alignment_failure')
    by_event = {e['id']: d for e, d in zip(requested, decisions)}
    checkpoints = [e['id'] for e in requested if by_event[e['id']]['stage'].startswith('return_') or by_event[e['id']]['stage'] == 'finish']
    if not checkpoints:
        raise ValueError('source_checkpoint_not_reached')
    first = checkpoints[0]
    for e, d in zip(requested, decisions):
        if e['id'] < first and not d['correct']:
            raise ValueError('prefix_decision_failure')
    prefix_physical = [r for r in result['physical_executions'] if not r['stage'].startswith('selected_station_')]
    if not all(r['result']['success'] for r in prefix_physical):
        raise ValueError('prefix_physical_failure')
    rollovers = []
    for p in sorted(source.glob('rollover-*/messages-before.json'), key=lambda p: int(p.parent.name.split('-')[-1])):
        messages = json.loads(p.read_text())
        ids = [int(n) for m in messages if m.get('role') == 'user'
               for n in re.findall(r'(?:^|\n)Event (\d+):', str(m.get('content', '')))]
        if not ids:
            raise ValueError('source_rollover_missing_event')
        if max(ids) < first:
            rollovers.append(max(ids))
    if len(rollovers) != result['planned_rollovers']:
        raise ValueError('source_rollover_alignment_failure')
    # result/expected labels are evaluator-private. Only public events and actual
    # source choices are ever supplied to Agent.
    return {'source': str(source), 'source_result_sha256': hashlib.sha256((source/'result.json').read_bytes()).hexdigest(),
            'case': result['case'], 'history': result['history'], 'jobs': result['intermediate_jobs'],
            'events': events, 'decisions': by_event, 'rollovers_after': rollovers,
            'checkpoint_ids': checkpoints, 'planned_checkpoints': result['planned_checkpoint'],
            'source_status': result['status'], 'omitted_answer_free_format_repair_event_ids': repairs,
            'existing_executor_receipts_enriched_at_feedback_events': receipt_ids,
            'protocol_version': 'explicit-skill-scope-v2'}


async def evaluate(source, output, policy_path, arm='memrsi'):
    from agent_adapter import Agent
    from runtime_config import usage_totals
    data = fixture(source)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    dump(output / 'fixture-audit.json', {k: v for k, v in data.items() if k not in ('events','decisions')})
    a = None
    r = {'status': 'running', 'scope': 'controlled history / decision replay; no physical actions executed',
         'source': str(source), 'available_checkpoints': len(data['checkpoint_ids']),
         'original_planned_checkpoints': data['planned_checkpoints'],
         'observed': 0, 'correct': 0, 'passed': False, 'decisions': [],
         'operator_rebuild': 'from empty memory, before the first archive; no gold memory injected',
         'prefix': 'recorded real public observations and executed actions, teacher-forced'}
    try:
        a = Agent(arm, output, memory_policy=policy_path if arm == 'memrsi' else None)
        first, last = data['checkpoint_ids'][0], data['checkpoint_ids'][-1]
        for e in data['events']:
            if e['id'] > last:
                break
            d = data['decisions'].get(e['id'])
            if e['id'] < first:
                if d:
                    # Only the actually executed public choice is included, never d['expected'].
                    await a.replay_observe(e['text'], d['choice'])
                else:
                    await a.observe_only(e['text'], {})
            elif d:
                r['observed'] += 1
                choice = await a.turn(e['text'], {}, decision=True)
                correct = choice['skill'] == d['expected']
                r['correct'] += int(correct)
                r['decisions'].append({'stage': d['stage'], 'choice': choice,
                                       'expected': d['expected'], 'correct': correct})
                if not correct:
                    r['status'] = 'decision_failure'
                    r['stop_reason'] = 'divergent_action_no_borrowed_feedback'
                    break
                if choice['skill'] == 'finish':
                    break
                if choice['skill'] != d['choice']['skill'] and e['id'] != last:
                    r['status'] = 'replay_suffix_unavailable'
                    break
            else:
                await a.observe_only(e['text'], {})
            if e['id'] in data['rollovers_after']:
                await a.rollover()
        if r['status'] == 'running':
            r['passed'] = r['correct'] == r['available_checkpoints']
            r['status'] = 'passed_saved_checkpoints' if r['passed'] else 'replay_incomplete'
        r.update(model_calls=a.provider.calls, policy_sha256=a.policy_hash)
    except Exception as e:
        r['status'] = 'infrastructure_failure' if str(e) in ('provider_error','model_admission_wait_timeout','agent_call_budget_exhausted','native_session_archival_failed') else 'protocol_failure'
        r['error_type'] = type(e).__name__
        r['error_code'] = str(e) if str(e) in ('provider_error','model_admission_wait_timeout','agent_call_budget_exhausted','native_session_archival_failed','action_protocol_failure','guidance_protocol_failure','guidance_review_protocol_failure','guidance_grounding_failure') else 'replay_error'
    finally:
        if a:
            await a.close()
        r.update(usage_totals(output))
        dump(output / 'result.json', r)
    return r


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--source', required=True)
    p.add_argument('--output', required=True); p.add_argument('--policy', required=True)
    a = p.parse_args(); asyncio.run(evaluate(a.source, a.output, a.policy))
