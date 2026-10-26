"""Small learned edits, evaluated through repeated archival and full decision suffixes."""
import asyncio
import copy
import json
from pathlib import Path
from durable_queue import read
from replay import dump
from stream_design import SEED_PROCEDURES, compile_procedures, development_rows
from memory_policy import digest
from feedback_learning import screen_generic
from optimizer_context import clip, prepare
from targeted_requests import cached_structured
from structured_feedback import CRITIC
from trajectory_replay import fixture, evaluate, lines
from model_provider import LEARNING_LEDGER

PATCH_SCHEMA = {'type': 'object', 'properties': {
    'target': {'type': 'string', 'enum': ['guidance', 'update'], 'maxLength': 20},
    'anchor': {'type': 'string', 'maxLength': 450},
    'replacement': {'type': 'string', 'maxLength': 450},
    'rationale': {'type': 'string', 'maxLength': 600}},
    'required': ['target', 'replacement', 'rationale'], 'additionalProperties': False}


def apply_edit(parent, patch):
    if not set(PATCH_SCHEMA['required']) <= set(patch) or set(patch)-set(PATCH_SCHEMA['properties']) or patch['target'] not in ('guidance', 'update'):
        raise ValueError('invalid_edit_fields')
    target = patch['target'];old = parent[target];anchor = patch.get('anchor', '');replacement = patch['replacement']
    if not isinstance(anchor, str) or not isinstance(replacement, str):
        raise ValueError('invalid_edit_type')
    if len(replacement) > 450 or len(anchor) > min(450, int(len(old) * .35)):
        raise ValueError('edit_not_local')
    if anchor and old.count(anchor) != 1:
        raise ValueError('anchor_not_unique')
    new = old.replace(anchor, replacement, 1) if anchor else old + '\n' + replacement
    if new.strip() == old.strip():
        raise ValueError('unchanged_edit')
    value = copy.deepcopy(parent);value[target] = new
    policy = compile_procedures(value);screen_generic(policy)
    return value, policy


def choose_sources(rows, maximum=4):
    """Development-only stratification: failures and successful regression controls."""
    eligible = [];excluded = []
    for row in sorted(rows, key=lambda r: r['trial_id']):
        try:
            f = fixture(row['output']);f['id'] = row['trial_id'];f['source_status'] = row['status']
            eligible.append(f)
        except (ValueError, KeyError, FileNotFoundError) as e:
            excluded.append({'id': row['trial_id'], 'status': row['status'], 'reason': type(e).__name__})
    bad = [f for f in eligible if f['source_status'] == 'decision_failure']
    good = [f for f in eligible if f['source_status'] == 'success']
    selected = bad[:2] + good[:2]
    selected += [f for f in eligible if f not in selected][:max(0, maximum - len(selected))]
    return selected[:maximum], excluded


def evidence(f):
    """Read FIRST source error, not the last convenient finish decision."""
    root = Path(f['source']);result = read(root/'result.json')
    decisions = f['decisions'];bad = [(e, d) for e, d in decisions.items() if not d['correct']]
    eid, choice = bad[0] if bad else (min(f['targets']), decisions[min(f['targets'])])
    guides = lines(root/'guidance-events.jsonl')
    guide = next((g for g in guides if g['current_request'].startswith(f'Event {eid}:')), {})
    archives = []
    for p in root.glob('rollover-*/audit.json'):
        a = read(p)
        if a['success'] and a['last_received_event'] < eid:
            archives.append((a['last_received_event'], p.parent))
    last = max(archives, default=(0, None))[1]
    return {'id': f['id'], 'source_status': result['status'], 'first_error_event': eid if bad else None,
        'source_policy': read(root/'applied-memory-policy.json'),
        'source_decision': {k: choice.get(k) for k in ('skill', 'correct', 'expected_private', 'session')},
        'memory_before_archive': (last/'memory-before.md').read_text() if last else '',
        'memory_after_archive': guide.get('long_memory', ''),
        'selected_evidence': guide.get('generated', {}),
        'archive_messages': read(last/'messages-before.json', []) if last else [],
        'diagnostic_only_expected_action_never_actor_input': True}


def proposal_data(parent, fs, credits):
    raw = [evidence(f) for f in fs]
    for cap in (650, 400, 220, 120):
        packed = []
        for item in raw:
            v = dict(item)
            for key in ('memory_before_archive', 'memory_after_archive', 'selected_evidence', 'archive_messages'):
                v[key] = clip(v[key], cap)
            v['excerpts_may_omit_evidence'] = True;packed.append(v)
        data = {'parent': parent, 'source_failures_and_controls': packed,
                'previous_actual_trajectory_effects': credits,
                'constraint': 'Return one exact local edit. Omitting anchor appends. Preserve at least 65% of existing text. Each final operator <=1600 characters.'}
        try:
            _, _, audit = prepare('x ' * 240, data, PATCH_SCHEMA)
            if audit['after_tokens'] < 8200:
                return data
        except ValueError:
            pass
    raise ValueError('trajectory_evidence_cannot_fit')


async def replay_case(f, out, policy, budget, wait_gateway):
    out = Path(out);out.mkdir(parents=True, exist_ok=True)
    if (out/'result.json').exists():return read(out/'result.json')
    attempts = []
    for n in range(1, 4):
        await asyncio.to_thread(wait_gateway)
        dest = out/f'attempt-{n:02d}'
        r = await evaluate(f, dest, policy, budget)
        if r['status'] == 'learning_budget_exhausted':
            raise RuntimeError('optimizer_call_budget')
        r = dict(r, logical_calls=read(dest/'calls.json', {}).get('calls', 0))
        attempts.append(r)
        # Known archive/protocol/capacity failures are evidence, not transport retries.
        if r['status'] != 'technical_failure':break
    result = dict(r, attempts=len(attempts),
        all_attempt_calls=sum(x['logical_calls'] for x in attempts),
        tokens=sum(x.get('model_input_tokens', 0)+x.get('model_output_tokens', 0) for x in attempts),
        cost_complete=all(x.get('model_cost_complete', False) for x in attempts))
    dump(out/'result.json', result);return result


async def paired(fs, out, parent, candidate, budget, wait_gateway, repetitions=2):
    out = Path(out);out.mkdir(parents=True, exist_ok=True)
    manifest = {'sources': [{'id': f['id'], 'sha256': f['sha256']} for f in fs],
                'parent': parent, 'candidate': candidate, 'repetitions': repetitions,
                'scope': 'full history reconstruction and all available autonomous suffix decisions'}
    old = read(out/'manifest.json')
    if old is not None and old != manifest:raise RuntimeError('trajectory_manifest_changed')
    dump(out/'manifest.json', manifest);rows = []
    for i, f in enumerate(fs):
        for rep in range(repetitions):
            order = [('parent', parent), ('candidate', candidate)]
            if (i+rep) % 2:order.reverse()
            rs = await asyncio.gather(*(replay_case(f, out/f"{f['id']}-r{rep}-{k}", p, budget, wait_gateway) for k, p in order))
            rows.extend(dict(r, case=f['id'], repeat=rep, policy=k) for r, (k, _) in zip(rs, order))
            dump(out/'rows.json', rows)
    return rows


def select(rows, expected_pairs):
    groups = {}
    for r in rows:
        g = groups.setdefault((r['case'], r['repeat']), {})
        if r['policy'] in g:raise ValueError('duplicate_trajectory_arm')
        g[r['policy']] = r
    valid = [g for g in groups.values() if set(g) == {'parent', 'candidate'} and
             all(x['status'] not in ('technical_failure', 'unclassified_failure', 'learning_budget_exhausted') for x in g.values())]
    for g in valid:
        if g['parent']['planned'] != g['candidate']['planned']:raise ValueError('checkpoint_denominator_changed')
    totals = {k: {name: sum(g[k].get(name, 0) for g in valid) for name in ('correct', 'answered', 'planned')} for k in ('parent', 'candidate')}
    complete = {k: sum(g[k]['status'] == 'completed' for g in valid) for k in ('parent', 'candidate')}
    calls = {k: sum(r.get('all_attempt_calls', 0) for r in rows if r['policy'] == k) for k in ('parent', 'candidate')}
    cases = {}
    for g in valid:
        name = g['parent']['case'];v = cases.setdefault(name, {'parent': [], 'candidate': []})
        for k in v:v[k].append(g[k]['correct'] == g[k]['planned'] and g[k]['status'] == 'completed')
    persistent = [k for k, v in cases.items() if all(v['parent']) and not any(v['candidate'])]
    gain = totals['candidate']['correct']-totals['parent']['correct']
    cost_ok = calls['candidate'] <= 1.5*max(1, calls['parent'])
    return {'planned_pairs': expected_pairs, 'valid_pairs': len(valid), 'totals': totals,
            'completed_trajectories': complete, 'correct_gain': gain, 'persistent_regressions': persistent,
            'logical_calls': calls, 'cost_ok': cost_ok,
            'accepted': bool(expected_pairs and len(groups) == expected_pairs and len(valid) == expected_pairs and
                gain > 0 and complete['candidate'] >= complete['parent'] and not persistent and cost_ok),
            'scope': 'development evidence only; novel-task gains require heldout physical evaluation'}


async def run(out, experiment, budget, old_learning, prior):
    out = Path(out);out.mkdir(parents=True, exist_ok=True)
    if (out/'report.json').exists():return read(out/'report.json')
    prior = Path(prior);ledger = out/'learning-call-ledger.json'
    if not ledger.exists():
        dump(ledger, read(prior/'learning/learning-call-ledger.json'))
        dump(out/'inherited-budget.json', {'source': str(prior), 'budget_not_reset': True})
    LEARNING_LEDGER.set(ledger)
    dump(out/'manifest.json', {'version': 'trajectory-v1.9', 'cycles': 2, 'development_each': 8,
        'proposal_each': 1, 'sources_each_max': 4, 'repetitions': 2, 'first_error_evidence': True,
        'all_available_checkpoints_scored': True, 'source_actions_teacher_forced_only_before_first_checkpoint': True,
        'old_validation_audited_for_design_not_independent_again': True, 'old_validation_not_read_by_optimizer': True,
        'formal48_never_used_for_learning': True, 'baseline_reruns': 0})
    current = copy.deepcopy(SEED_PROCEDURES);credits = [];promotions = 0
    for cycle in range(2):
        root = out/f'cycle-{cycle}';root.mkdir(exist_ok=True);parent = compile_procedures(current)
        dump(root/'parent-policy.json', parent)
        rows = [dict(r, gpu=2) for r in development_rows()[cycle*8:(cycle+1)*8]]
        experiment.state('trajectory_development', cycle=cycle)
        physical = await asyncio.to_thread(experiment.batch, rows, {'memrsi': root/'parent-policy.json'}, root/'physical')
        done = read(root/'selection.json')
        if done:
            if done['parent_hash'] != digest(parent):raise RuntimeError('trajectory_parent_changed')
            current = done['selected_procedures'];promotions += int(done['accepted']);credits.append(done['credit']);continue
        fs, excluded = choose_sources(physical)
        dump(root/'source-audit.json', {'eligible_selected': [f['id'] for f in fs], 'excluded': excluded,
                                       'source_selection': 'first two decision failures plus first two successes, fill deterministically'})
        effect = {'accepted': False, 'reason': 'no_eligible_sources'};chosen = current
        if fs:
            experiment.state('trajectory_local_edit', cycle=cycle)
            proposal = await cached_structured(root/'proposal',
                'Improve long/short mission memory with ONE LOCAL EDIT to Guidance or Update. '
                'Use the FIRST observed source failure and successful controls. Locate the earliest supported information problem; '
                'a source policy may differ from the current parent. A latest summary may be inaccurate, '
                'and a local completion may not complete its encompassing request: check supplied evidence, do not assume either cause. '
                'Preserve correct behavior and unaffected rules. Return target, exact unique anchor (omit to append), replacement, rationale. '
                'Do not encode concrete task names, objects, event IDs, orders, benchmark names, expected answers, '
                'or rules that force continuation/finish. Do not make changes unsupported by evidence. '
                'Assess effects across repeated archives and multiple decisions, not just the last decision.',
                proposal_data(current, fs, credits), PATCH_SCHEMA, experiment.wait_gateway)
            try:
                procedures, candidate = apply_edit(current, proposal)
            except ValueError as e:
                effect = {'accepted': False, 'reason': 'invalid_local_edit', 'code': str(e)}
            else:
                critic = await cached_structured(root/'critic',
                    'Check generic memory management rules: no task answers, concrete benchmark identities, '
                    'or mandatory finish/continuation overrides. Preserve user authority.', procedures, CRITIC, experiment.wait_gateway)
                if all(critic[k] for k in ('generic', 'no_task_answers', 'preserves_user_authority')):
                    dump(root/'candidate-policy.json', candidate)
                    experiment.state('trajectory_full_history_comparison', cycle=cycle)
                    probes = await paired(fs, root/'probes', parent, candidate, budget, experiment.wait_gateway)
                    effect = select(probes, len(fs)*2)
                    if effect['accepted']:chosen = procedures;promotions += 1
                else:effect = {'accepted': False, 'reason': 'critic_rejected'}
        credit = {'cycle': cycle, 'effect': effect}
        dump(root/'selection.json', {'parent_hash': digest(parent), 'accepted': effect['accepted'],
            'selected_procedures': chosen, 'credit': credit})
        current = chosen;credits.append(credit)
    policy = compile_procedures(current);dump(out/'candidate-policy.json', policy)
    report = {'status': 'candidate_ready_for_test' if promotions else 'no_accepted_update',
              'promotions': promotions, 'candidate_hash': digest(policy), 'credits': credits}
    dump(out/'report.json', report);return report
