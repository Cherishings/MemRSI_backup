"""Capacity calibration uses disjoint fictional jobs, never evaluation answers.

Selection is declared before calls: smallest capacity with complete recall in
both fixtures, at least twice the compact witness size. This is an engineering
pilot, not a statistical claim that this budget is optimal.
"""
import argparse, asyncio, json, math, time
from pathlib import Path
from run_queue import dump
from model_provider import Provider, MODEL
from memory_budget import BoundedStore, pair
from token_accounting import tokens, request_tokens, memory_tokens
from twenty_agent import TwentyAgent
from memory_policy import BASE
from twenty_protocol import restore_input, plan, reference_note

CANDIDATES = (512, 1024, 2048)
PROBE = [{'type': 'function', 'function': {'name': 'recall',
    'description': 'Extract these fields only from the supplied stored records.',
    'parameters': {'type': 'object', 'properties': {
        'remaining': {'type': 'array', 'items': {'type': 'string'}},
        'order': {'type': 'array', 'items': {'type': 'string'}},
        'cancelled': {'type': 'string'}, 'final': {'type': 'string'}},
        'required': ['remaining', 'order', 'cancelled', 'final'], 'additionalProperties': False}}}]

def fixture(index):
    names = ['elm', 'pine', 'oak', 'ash', 'fir']
    order = names[1:] + names[:1] if index == 0 else list(reversed(names))
    truth = {'remaining': [n + ':polish' for n in names], 'order': order,
             'cancelled': 'cedar', 'final': 'birch'}
    messages = [{'role': 'user', 'content':
        'For this workshop shift, each of elm, pine, oak, ash, fir needs washing then polishing. '
        'When the temporary orders end, finish the remaining work in the order elm, pine, oak, ash, fir. '
        'Afterwards inspect birch and close the shift. Also inspect cedar after birch.'}]
    for i, name in enumerate(names):
        messages += [{'role': 'user', 'content': f'Wash {name}, then pause its polishing.'},
            {'role': 'user', 'content': f'Execution receipt: {name} washing verified complete; polishing not performed.'}]
        for j in range(3):
            messages.append({'role': 'user', 'content':
                f'Temporary order W{i}-{j} completed: sorted supplies, delivered them, checked delivery. '
                f'Inspection readings: position {i * 0.12:.3f},{j * 0.07:.3f}; contact released; '
                'no work remains for this temporary order.'})
    messages += [{'role': 'user', 'content': 'Change the remaining work order to ' + ', '.join(order) +
                 '. This supersedes the earlier order.'},
                {'role': 'user', 'content': 'Cancel cedar inspection without replacement. Other work remains valid.'}]
    return messages, truth

async def run(a):
    out = Path(a.output); out.mkdir(parents=True, exist_ok=False)
    dump(out / 'preregistered-selection.json', {
        'persistent_candidates': CANDIDATES, 'fixtures_per_candidate': 2,
        'selection': 'smallest budget with all four recall fields correct in both fixtures and >=2x compact witness tokens',
        'active_candidates': [4096, 8192, 12288, 16384, 24576],
        'active_selection': 'smallest >=1.25x measured largest composed actor request or prior request, and >=8x selected persistent budget',
        'purpose': 'capacity sanity check, no PAOS-versus-MemRSI performance selection',
        'no_evaluation_answers_in_calibration_calls': True})
    rows = []
    for budget in CANDIDATES:
        for index in range(2):
            dest = out / f'long{budget}-fixture{index}'; dest.mkdir()
            provider = Provider(dest)
            store = BoundedStore(dest / 'workspace', budget, provider._append)
            messages, truth = fixture(index)
            dump(out / 'progress.json', {'status': 'calibrating', 'budget': budget,
                'fixture': index, 'completed': len(rows)})
            row = {'budget': budget, 'fixture': index, 'compact_witness_tokens': tokens(json.dumps(truth)),
                   'correct': False, 'status': 'running'}
            try:
                if not await store.consolidate(messages, provider, MODEL):
                    row['status'] = 'archive_or_capacity_failure'
                else:
                    response = await provider.chat(messages=[{'role': 'system', 'content':
                        'Read the supplied stored records. Extract the remaining job names as name:operation, '
                        'their required order, the cancelled job, and the final required job. '
                        'Use recall once. Do not invent missing information.'},
                        {'role': 'user', 'content': json.dumps(dict(zip(('memory', 'history'), pair(store))))}],
                        tools=PROBE, tool_choice='required')
                    calls = response.tool_calls or []
                    got = calls[0].arguments if len(calls) == 1 and calls[0].name == 'recall' else {}
                    fields = {k: (sorted(got.get(k, [])) == sorted(v) if k == 'remaining' and
                        isinstance(got.get(k), list) else got.get(k) == v) for k, v in truth.items()}
                    row.update(status='completed', correct=all(fields.values()), field_correct=fields,
                        stored_tokens=memory_tokens(*pair(store)), recall=got, expected_private=truth)
            except Exception as exc:
                row.update(status='infrastructure_failure', exception_type=type(exc).__name__)
            finally:
                await provider._client.close()
            rows.append(row); dump(out / 'rows.json', rows)
    required = 2 * max(r['compact_witness_tokens'] for r in rows)
    eligible = [b for b in CANDIDATES if b >= required and
                all(r['correct'] for r in rows if r['budget'] == b)]
    if not eligible:
        dump(out / 'report.json', {'status': 'blocked_capacity_calibration', 'rows': rows})
        return
    persistent = min(eligible)
    # Measure full request including bootstrap instructions, all seven scenes,
    # two current interactions, tools and maximum retained memory allowance.
    q = Path(a.qualification)
    scenes = json.loads((q / 'init0/first-recovery-scene.json').read_text())
    observations = {k: v['scene_observation'] for k, v in scenes.items()}
    probe_dir = out / 'input-sizing'; probe_dir.mkdir()
    agent = TwentyAgent('native', probe_dir, None,
                        {'persistent_tokens': persistent, 'active_input_tokens': 1000000})
    try:
        text = restore_input(observations)
        current = agent.loop.context.build_messages(history=[
            {'role': 'user', 'content': text},
            {'role': 'assistant', 'content': 'Selected service; awaiting execution feedback.'},
            {'role': 'user', 'content': 'Actual execution feedback: ' + json.dumps(observations)}],
            current_message=text, channel='cli', chat_id='capacity_probe')
        composed = request_tokens(current, agent.loop.tools.get_definitions()) + persistent + 1800
        # 1800-token reserve covers generated guidance, a tool response and formatting.
    finally:
        await agent.close()
    prior_sizes = []
    prior_root = Path(a.prior)
    for p in prior_root.glob('physical/evaluation/**/model-trace.jsonl'):
        for line in p.read_text().splitlines():
            req = json.loads(line).get('request', {})
            prior_sizes.append(request_tokens(req.get('messages', []), req.get('tools')))
    largest_prior = max(prior_sizes, default=0)
    floor = max(math.ceil(1.25 * max(composed, largest_prior)), 8 * persistent)
    choices = [v for v in (4096, 8192, 12288, 16384, 24576) if v >= floor]
    if not choices:
        dump(out / 'report.json', {'status': 'blocked_active_capacity', 'required_floor': floor, 'rows': rows})
        return
    config = {'schema': 1, 'persistent_tokens': persistent, 'active_input_tokens': min(choices),
        'output_tokens_per_call': 2048, 'tokenizer': 'o200k_base',
        'active_accounting': 'serialized input messages plus tool schemas, including long memory and guidance',
        'persistent_accounting': 'sum of MEMORY.md and HISTORY.md token counts', 'entry_limit': None,
        'selected_before_main_results': True, 'calibration_path': str(out)}
    dump(out / 'selected-budget.json', config)
    dump(out / 'report.json', {'status': 'completed', 'selected': config, 'rows': rows,
        'largest_prior_request_tokens': largest_prior, 'prior_requests_measured': len(prior_sizes),
        'composed_request_with_reserves': composed, 'active_required_floor': floor,
        'task_reference_note_tokens_evaluator_only': {h: tokens(reference_note(h)) for h in ('alpha', 'beta')},
        'limitation': 'Two fixtures per capacity establish feasibility only; not an optimal-budget estimate.'})
    dump(out / 'progress.json', {'status': 'completed', 'selected': config})

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--output', required=True)
    p.add_argument('--qualification', required=True); p.add_argument('--prior', required=True)
    asyncio.run(run(p.parse_args()))
