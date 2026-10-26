"""Learn only G/U text on the byte-identical successful bounded-memory runtime.

Development source trajectories never contain the 48 comparison cases. Every
candidate rebuilds its own memory; teacher forcing ends at the first checkpoint.
Test traces inspected by humans are explicitly not an untouched benchmark now.
"""
import asyncio
import copy
import json
from pathlib import Path
from durable_queue import read
from replay import dump
from stream_design import SEED_PROCEDURES, compile_procedures, development_rows
from trajectory_evolution import select, replay_case, paired
from bounded_edits import PATCH_SCHEMA, apply_edit, recover_last_submission
from trajectory_replay import fixture, lines
from targeted_requests import cached_structured
from structured_feedback import CRITIC, StructuredFailure
from optimizer_context import clip, prepare
from model_provider import LEARNING_LEDGER
from transition_diagnosis import diagnosed_packet

SYSTEM = (
    'Improve ONE operator of a working long/short task-memory agent with ONE LOCAL EDIT. '
    'The memory store, archive interface, capacity, actor and physical executor are fixed. '
    'Guidance selects at most five existing evidence IDs; Update writes the original compact '
    'mission/tasks memory using save_memory. Do not invent transactions, tools, schemas or validators. '
    'Use current-parent actual archive and guidance evidence, not old source policy behavior. '
    'If received facts disappear or stay obsolete after archive, change Update; if correct facts '
    'are retained but not selected, change Guidance. If selected facts are correct but the actor '
    'errs, do not claim an archive fault. Distinguish supported diagnosis from uncertainty. '
    'Preserve working rules; no wholesale rewrite. Runtime rules must be executable by their '
    'operator, not instructions to inspect a hidden evaluator or perform optimizer diagnosis. '
    'No concrete tasks, objects, tables, event IDs, order answers or benchmark names in rules. '
    'No compulsory finish/continuation, no hard action veto. Return target, optional exact unique '
    'anchor, replacement, rationale. Replacement and rationale each <=1200 characters; '
    'anchor <=450 characters and at most35% of the existing operator. Each final operator <=1600 characters. '
    'Use failures AND successful controls. Prefer a small evidence-supported correction. '
    'The packet contains exact-quote-checked transition diagnoses and all previous edit gains/losses. '
    'Diagnoses are hypotheses: use their witnesses and uncertainty. Fix the earliest supported information defect. '
    'Do not repeatedly sharpen Guidance if Update has already lost or corrupted the requirement. '
    'Archived summaries are claims, not automatically authoritative user instructions. '
    'Use previous rejected edits as negative feedback: preserve what worked and avoid their failure mechanism. '
    'An actor-use error cannot be repaired by blindly changing archive rules. Do not copy concrete case contents into rules.'
)


async def safe_structured(path, system, data, schema, wait_gateway):
    """Malformed proposal/critic is a rejected candidate, not a queue crash.

    Transport and budget exceptions still propagate; they are not model quality.
    A failed format retry is terminal across restarts; no fresh sampling budget.
    """
    path=Path(path)
    rejected=read(path/'candidate-rejection.json')
    if rejected:
        return None,rejected
    if not (path/'value.json').exists():
        previous=sorted(path.glob('attempt-*/format-rejection-1.json'))
        if previous:
            rejected=dict(code=read(previous[-1])['code'],reason='format_attempts_exhausted',new_model_calls=0)
            dump(path/'candidate-rejection.json',rejected)
            return None,rejected
    try:
        return await cached_structured(path,system,data,schema,wait_gateway),None
    except StructuredFailure as ex:
        rejected=dict(code=str(ex),reason='invalid_structured_candidate')
        dump(path/'candidate-rejection.json',rejected)
        return None,rejected


def source_sets(prior):
    training = []
    all_rows = []
    for cycle in range(2):
        root = Path(prior)/'learning'/f'cycle-{cycle}'
        manifest = read(root/'probes/manifest.json')
        rows = read(root/'probes/rows.json')
        fs = []
        for source in manifest['sources']:
            row = next(r for r in rows if r['case'] == source['id'] and r['policy'] == 'parent')
            f = fixture(row['source']); f['id'] = source['id']
            if f['sha256'] != source['sha256']:
                raise RuntimeError('development_source_changed')
            fs.append(f)
        training.append(fs)
        all_rows.extend(read(root/'physical/rows.json'))
    used = {f['id'] for fs in training for f in fs}
    allowed = {r['trial_id']: r['history'] for r in development_rows()}
    if not used <= set(allowed):
        raise RuntimeError('nondevelopment_source')
    validation = []; histories = set()
    for row in sorted(all_rows, key=lambda r: r['trial_id']):
        if row['trial_id'] in used or row['trial_id'] not in allowed or row['history'] in histories:
            continue
        try:
            f = fixture(row['output'])
        except (ValueError, KeyError, FileNotFoundError):
            continue
        f['id'] = row['trial_id']; validation.append(f); histories.add(row['history'])
        if len(validation) == 2:
            break
    if len(validation) != 2:
        raise RuntimeError('missing_separate_validation_sources')
    return training, validation


def actual_evidence(f, row, root):
    """Optimizer-only trace. Evaluator answers never enter runtime G/U or actor."""
    dest = Path(root)/f"{row['case']}-r{row['repeat']}-parent"/f"attempt-{row['attempts']:02d}"
    first = next((d for d in row.get('decisions', []) if not d['correct']), None)
    eid = first['event'] if first else max((d['event'] for d in row.get('decisions', [])), default=min(f['targets']))
    guides = lines(dest/'guidance-events.jsonl')
    guide = next((g for g in guides if g['current_request'].startswith(f'Event {eid}:')), {})
    archives = []
    for p in dest.glob('rollover-*/audit.json'):
        a = read(p)
        if a['last_received_event'] < eid:
            archives.append((a['last_received_event'], p.parent))
    recent = []
    for event, p in sorted(archives)[-3:]:
        recent.append(dict(last_event=event,
            before=(p/'memory-before.md').read_text(), after=(p/'memory-after.md').read_text(),
            # All received user instructions in this archive are retained below.
            user_messages=[m['content'] for m in read(p/'messages-before.json', [])
                           if m['role'] == 'user' and 'Execution feedback:' not in m['content']]))
    public = [e['text'].split('Current scene')[0].strip() for e in f['events']
              if e['id'] <= eid and 'Execution feedback:' not in e['text']]
    return dict(case=row['case'], repeat=row['repeat'], status=row['status'], correct=row['correct'],
                planned=row['planned'], error_code=row.get('error_code'),
                first_wrong_decision=dict(first, expected_private=f['decisions'][eid]['expected_private']) if first else None,
                public_instructions=public, archives=recent, guidance=guide,
                scope='current parent development replay; expected choice is optimizer-only')


def packet(parent, fs, rows, root, credits):
    # One actual repetition per source, prioritizing its first error. All repeats
    # still count in selection; this is only bounded optimizer evidence packing.
    evidence = []
    for f in fs:
        rr = [r for r in rows if r['case'] == f['id']]
        chosen = next((r for r in rr if r['status'] != 'completed'), rr[0])
        evidence.append(actual_evidence(f, chosen, root))
    for cap in (500, 300, 160, 80):
        packed = []
        for e in evidence:
            v = copy.deepcopy(e)
            for a in v['archives']:
                a['before'] = clip(a['before'], cap)
                a['after'] = clip(a['after'], cap)
                a['user_messages'] = [x.split('Current scene')[0].strip() for x in a['user_messages']]
            g = v['guidance']
            v['guidance'] = dict(long_memory=clip(g.get('long_memory', ''), cap*2),
                                 selected_evidence=clip(g.get('generated', {}), cap),
                                 current_request=g.get('current_request', '').split('Current scene')[0])
            v['memory_excerpts_may_omit_evidence'] = True; packed.append(v)
        data = dict(parent=parent, actual_parent_evidence=packed, previous_effects=credits,
                    runtime_interface='unchanged bounded memory and original save_memory; no DeltaStore',
                    rule_character_limit=1600)
        try:
            _, _, audit = prepare(SYSTEM, data, PATCH_SCHEMA)
            if audit['after_tokens'] <= 9000:
                return data
        except ValueError:
            pass
    raise RuntimeError('bounded_optimizer_evidence_does_not_fit')


def validation_gate(rows, expected_pairs):
    effect = select(rows, expected_pairs)
    # No 100% requirement. An adopted development edit must at least preserve
    # aggregate performance on the reserved development source set.
    effect['passed'] = bool(effect['valid_pairs'] == expected_pairs and
        effect['correct_gain'] >= 0 and
        effect['completed_trajectories']['candidate'] >= effect['completed_trajectories']['parent'] and
        not effect['persistent_regressions'] and effect['cost_ok'])
    effect['scope'] = 'reserved development regression check, not an untouched generalization benchmark'
    return effect


def reuse_parent_if_identical(source,root,parent):
    """Reuse every existing parent result only for byte-identical policy; no cherry-picking."""
    source=Path(source);root=Path(root)
    if read(source/'parent-policy.json')!=parent:return False
    rows=read(source/'parent-rows.json',[])
    if len(rows)!=8:raise RuntimeError('parent_reuse_incomplete')
    for row in rows:
        result=read(source/'parent-replays'/f"{row['case']}-r{row['repeat']}-parent"/'result.json')
        if not result or any(result.get(k)!=row.get(k) for k in ('status','correct','planned','attempts')):
            raise RuntimeError('parent_reuse_result_mismatch')
    target=root/'parent-replays';original=source/'parent-replays'
    if target.exists():
        if not target.is_symlink() or target.resolve()!=original.resolve():raise RuntimeError('parent_reuse_target_changed')
    else:target.symlink_to(original,target_is_directory=True)
    dump(root/'parent-reuse.json',dict(source=str(source),rows=8,all_terminal_results_retained=True,policy_exact=True,new_parent_calls=0))
    return True


async def run(out, controller, budget, source_prior, budget_prior):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    if (out/'report.json').exists():
        return read(out/'report.json')
    ledger = out/'learning-call-ledger.json'
    if not ledger.exists():
        inherited = read(Path(budget_prior)/'learning/learning-call-ledger.json')
        if inherited['limit'] != 9745 or inherited['calls'] < 6463:
            raise RuntimeError('inherited_budget_mismatch')
        dump(ledger, inherited)
        dump(out/'inherited-budget.json', dict(source=str(budget_prior), ledger=inherited, reset=False))
    token = LEARNING_LEDGER.set(ledger)
    try:
        training, validation = source_sets(source_prior)
        dump(out/'manifest.json', dict(version='bounded-v2.2', cycles=2, repetitions=2,
            training=[[dict(id=f['id'], sha256=f['sha256']) for f in fs] for fs in training],
            validation=[dict(id=f['id'], sha256=f['sha256']) for f in validation],
            parent='exact previously successful fixed policy', architecture_changed=False,
            formal48_read_by_optimizer=False, old_development_reuse_disclosed=True))
        current = copy.deepcopy(SEED_PROCEDURES); credits = []; promotions = 0
        for cycle, fs in enumerate(training):
            root = out/f'cycle-{cycle}'; root.mkdir(exist_ok=True)
            done = read(root/'selection.json')
            if done:
                current = done['selected']; promotions += int(done['effect']['accepted'])
                credits.append(done['effect']); continue
            parent = compile_procedures(current); dump(root/'parent-policy.json', parent)
            reuse_parent_if_identical(Path(budget_prior)/'learning'/f'cycle-{cycle}',root,parent)
            parent_rows = []
            for f in fs:
                controller.state('bounded_parent_replay', cycle=cycle, source=f['id'])
                rs = await asyncio.gather(*(replay_case(f, root/'parent-replays'/f"{f['id']}-r{rep}-parent",
                    parent, budget, controller.wait_gateway) for rep in range(2)))
                parent_rows += [dict(r, case=f['id'], repeat=rep, policy='parent') for rep, r in enumerate(rs)]
                dump(root/'parent-rows.json', parent_rows)
            controller.state('bounded_transition_diagnosis',cycle=cycle)
            data = await diagnosed_packet(current,fs,parent_rows,root/'parent-replays',root/'diagnosis',
                credits,Path(budget_prior)/'learning'/f'cycle-{cycle}',safe_structured,controller.wait_gateway)
            dump(root/'feedback-packet.json', data)
            if not any(d['target'] in ('update','guidance') for trace in data['transition_diagnoses'] for d in trace['diagnoses']):
                effect=dict(accepted=False,reason='no_supported_memory_operator_diagnosis')
                dump(root/'selection.json',dict(selected=current,effect=effect));credits.append(effect)
                continue
            controller.state('bounded_local_rule_learning', cycle=cycle)
            recovered=None  # New evidence-driven proposal; no recovery of rejected old edits.
            if recovered is not None:
                patch,rejection=recovered,None
            else:
                patch,rejection=await safe_structured(root/'proposal', SYSTEM, data, PATCH_SCHEMA, controller.wait_gateway)
            chosen = current; effect = dict(accepted=False, reason='invalid_edit')
            if rejection:
                effect=dict(accepted=False,reason='proposal_rejected',details=rejection)
                dump(root/'selection.json',dict(selected=current,effect=effect))
                credits.append(effect)
                continue
            try:
                procedures, candidate = apply_edit(current, patch)
            except (ValueError, StructuredFailure) as ex:
                effect['code'] = str(ex)
            else:
                critic,rejection = await safe_structured(root/'critic',
                    'Check generic runtime memory rules: no concrete task answers, benchmark identities, '
                    'mandatory action override or hidden validator access. Preserve user authority.',
                    procedures, CRITIC, controller.wait_gateway)
                if not rejection and all(critic[k] for k in ('generic', 'no_task_answers', 'preserves_user_authority')):
                    dump(root/'candidate-policy.json', candidate); rows = list(parent_rows)
                    for f in fs:
                        controller.state('bounded_candidate_replay', cycle=cycle, source=f['id'])
                        rs = await asyncio.gather(*(replay_case(f, root/'candidate-replays'/f"{f['id']}-r{rep}-candidate",
                            candidate, budget, controller.wait_gateway) for rep in range(2)))
                        rows += [dict(r, case=f['id'], repeat=rep, policy='candidate') for rep, r in enumerate(rs)]
                        dump(root/'paired-rows.json', rows)
                    effect = select(rows, len(fs)*2)
                    effect['edited_operator'] = patch['target']
                    if effect['accepted']:
                        chosen = procedures; promotions += 1
                else:
                    effect = dict(accepted=False, reason='critic_rejected',details=rejection)
            dump(root/'selection.json', dict(selected=chosen, effect=effect))
            current = chosen; credits.append(effect)
        dump(out/'selected-procedures.json', current)
        policy = compile_procedures(current); dump(out/'selected-policy.json', policy)
        check = None
        if promotions:
            controller.state('bounded_reserved_validation')
            rows = await paired(validation, out/'validation', compile_procedures(SEED_PROCEDURES),
                                policy, budget, controller.wait_gateway, repetitions=2)
            check = validation_gate(rows, len(validation)*2)
            dump(out/'validation-check.json', check)
        ready = promotions > 0 and check['passed']
        if ready:
            dump(out/'candidate-policy.json', policy)
        report = dict(status='candidate_ready_for_test' if ready else 'no_qualified_update',
                      promotions=promotions, credits=credits, validation=check,
                      fixed_architecture_restored=True, repair_not_counted_as_rsi_gain=True)
        dump(out/'report.json', report); return report
    finally:
        LEARNING_LEDGER.reset(token)
