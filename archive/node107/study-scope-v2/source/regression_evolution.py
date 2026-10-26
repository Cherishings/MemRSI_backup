"""Learn from the last candidate's actual regressions; retain verified parent caches.
Development reuse is explicit, never counted as new independent evidence.
Actor, archival interface, capacity, replay, and physical scoring stay unchanged.
"""
import asyncio
import hashlib
import json
from pathlib import Path
from durable_queue import read
from replay import dump
from trajectory_evolution import apply_edit, select, replay_case, PATCH_SCHEMA
from trajectory_replay import fixture, lines
from stream_design import SEED_PROCEDURES, compile_procedures
from targeted_requests import cached_structured
from structured_feedback import CRITIC
from optimizer_context import clip, prepare
from model_provider import LEARNING_LEDGER
from run_queue import ROOT

SYSTEM = ('Repair ONE generic memory operator using the actual regressions of previous learned rules. '
    'Distinguish preservation of user constraints, tracking verified progress, evidence selection, and actor use. '
    'Compare the failed attempt with the paired parent; independent archival sampling prevents claiming a single cause. '
    'Locate contradictions between remembered requirements and progress summaries. Do not assume a local pause '
    'changes global priority, and do not assume this is the cause unless the supplied records support it. '
    'Return one local edit to the SEED parent, not to a rejected candidate. Preserve unaffected behavior. '
    'No concrete objects, table names, event IDs, tool choices, benchmark answers, or compulsory continue/finish rules. '
    'Specify the information relationship to preserve or select rather than adding a vague reminder. '
    'Each operator <=1600 characters. Return target, optional exact unique anchor, replacement <=450 characters, rationale.')


def verify_runtime(prior_code):
    # Every v1.9 Python module is retained byte-for-byte. New orchestration only.
    checks = {}
    for old in sorted(Path(prior_code).glob('*.py')):
        current = ROOT/old.name
        if not current.exists() or current.read_bytes() != old.read_bytes():
            raise RuntimeError('cached_runtime_changed:'+old.name)
        checks[old.name] = hashlib.sha256(old.read_bytes()).hexdigest()
    return checks


def plan(prior, budget):
    prior = Path(prior);parent = compile_procedures(SEED_PROCEDURES);jobs = []
    if read(prior/'budget.json') != read(budget):raise RuntimeError('cached_budget_changed')
    for cycle, reps in ((0, (0, 1)), (1, (0,))):
        folder = prior/'learning'/f'cycle-{cycle}'/'probes'
        manifest = read(folder/'manifest.json')
        if manifest['parent'] != parent:raise RuntimeError('cached_parent_changed')
        sources = manifest['sources']
        rows = read(folder/'rows.json')
        for src in sources:
            for rep in reps:
                name = f"{src['id']}-r{rep}-parent";cache = folder/name
                result = read(cache/'result.json')
                matches = [r for r in rows if r['case']==src['id'] and r['repeat']==rep and r['policy']=='parent']
                if len(matches)!=1 or any(matches[0].get(k)!=result.get(k) for k in result):
                    raise RuntimeError('cached_result_mismatch')
                if result['status'] in ('technical_failure','unclassified_failure','learning_budget_exhausted'):
                    raise RuntimeError('cached_parent_invalid')
                f = fixture(result['source']);f['id']=src['id']
                if f['sha256'] != src['sha256']:raise RuntimeError('cached_source_changed')
                jobs.append(dict(cycle=cycle, repeat=rep, fixture=f, cache=str(cache), parent=result))
    if len(jobs)!=12:raise RuntimeError('development_plan_changed')
    return jobs


def at_event(folder, eid):
    guides = lines(Path(folder)/'guidance-events.jsonl')
    g = next((g for g in guides if g['current_request'].startswith(f'Event {eid}:')), {})
    return dict(memory=g.get('long_memory',''), selected=g.get('generated',{}),
                selection_available=bool(g), short_message_count=g.get('short_message_count'))


def feedback(prior):
    records=[];prior=Path(prior)
    # Deterministic first regression per source in each round, not outcome picking on test data.
    for cycle in (0,1):
        root=prior/'learning'/f'cycle-{cycle}';rows=read(root/'probes/rows.json');seen=set()
        for row in sorted(rows,key=lambda r:(r['case'],r['repeat'],r['policy'])):
            if row['policy']!='candidate' or row['case'] in seen:continue
            peer=next(r for r in rows if r['case']==row['case'] and r['repeat']==row['repeat'] and r['policy']=='parent')
            if row['correct']>=peer['correct']:continue
            seen.add(row['case']);name=f"{row['case']}-r{row['repeat']}"
            attempt=Path(root/'probes'/f'{name}-candidate')/f"attempt-{row['attempts']:02d}"
            parent_attempt=Path(root/'probes'/f'{name}-parent')/f"attempt-{peer['attempts']:02d}"
            bad=next((x for x in row.get('decisions',[]) if not x['correct']),None)
            eid=bad['event'] if bad else None
            item=dict(cycle=cycle,case=row['case'],repeat=row['repeat'],
                rejected_edit=read(root/'proposal/value.json'),
                previous_effect=read(root/'selection.json')['credit']['effect'],
                error_code=row.get('error_code'),error_phase=row.get('failure_phase'),
                candidate_decision=bad,parent_decision=next((x for x in peer.get('decisions',[]) if x['event']==eid),None),
                candidate_evidence=at_event(attempt,eid) if eid else {},
                parent_evidence=at_event(parent_attempt,eid) if eid else {},
                source=str(attempt),evidence_is_development_only=True)
            records.append(item)
    return records


def proposal_input(prior):
    raw=feedback(prior)
    for cap in (800,500,300,160):
        packed=[]
        for r in raw:
            v=dict(r)
            for side in ('candidate_evidence','parent_evidence'):
                v[side]={k:clip(value,cap) if k in ('memory','selected') else value for k,value in r[side].items()}
            v['excerpt_may_omit_evidence']=True;packed.append(v)
        data=dict(parent=SEED_PROCEDURES,actual_candidate_regressions=packed,
                  previously_rejected_rules_are_not_parent=True,
                  independent_archive_sampling=True,formal_test_data_unavailable=True)
        try:
            _,_,audit=prepare(SYSTEM,data,PATCH_SCHEMA)
            if audit['after_tokens']<8200:return data,audit
        except ValueError:pass
    raise ValueError('regression_evidence_cannot_fit')


async def evaluate_jobs(jobs,out,candidate,budget,controller):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);rows=[]
    # Two concurrent API requests, bounded by the existing shared request locks.
    for offset in range(0,len(jobs),2):
        batch=jobs[offset:offset+2]
        results=await asyncio.gather(*(replay_case(j['fixture'],out/f"{j['fixture']['id']}-r{j['repeat']}-candidate",candidate,budget,controller.wait_gateway) for j in batch))
        for j,r in zip(batch,results):
            info=dict(case=j['fixture']['id'],repeat=j['repeat'])
            parent=dict(j['parent'],**info,policy='parent',historical_cache=j['cache'],new_execution=False)
            rows.extend([parent,dict(r,**info,policy='candidate',new_execution=True)])
        dump(out/'rows.json',rows)
        controller.state('regression_full_history_comparison',finished_pairs=len(rows)//2,planned_pairs=len(jobs))
    return rows


async def run(out,controller,budget,prior_record):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);prior=Path(prior_record['result'])
    if (out/'report.json').exists():return read(out/'report.json')
    checks=verify_runtime(prior_record['code']);dump(out/'unchanged-runtime.json',checks)
    ledger=out/'learning-call-ledger.json'
    if not ledger.exists():
        previous=read(prior/'learning/learning-call-ledger.json');dump(ledger,previous)
        dump(out/'inherited-budget.json',dict(source=str(prior),ledger=previous,budget_not_reset=True))
    LEARNING_LEDGER.set(ledger)
    jobs=plan(prior,budget)
    manifest=dict(version='regression-feedback-v1.10',proposals=1,
        planned_pairs=12,source_repetitions={'cycle0':2,'cycle1':1},
        parent_policy=compile_procedures(SEED_PROCEDURES),
        cached_parent_results=[dict(source=j['cache'],sha256=hashlib.sha256((Path(j['cache'])/'result.json').read_bytes()).hexdigest()) for j in jobs],
        prior_evidence_not_new_independent_samples=True,comparison_not_simultaneous=True,
        all_cases_development_not_validation=True,formal48_never_used_for_learning=True,
        original_selection_criterion_unchanged=True)
    old=read(out/'manifest.json')
    if old is not None and old!=manifest:raise RuntimeError('regression_manifest_changed')
    dump(out/'manifest.json',manifest)
    data,audit=proposal_input(prior);dump(out/'feedback-packet.json',data);dump(out/'input-audit.json',audit)
    controller.state('regression_local_edit',development_regressions=len(data['actual_candidate_regressions']))
    patch=await cached_structured(out/'proposal',SYSTEM,data,PATCH_SCHEMA,controller.wait_gateway)
    try:procedures,candidate=apply_edit(SEED_PROCEDURES,patch)
    except ValueError as e:
        report=dict(status='no_accepted_update',promotions=0,reason='invalid_local_edit',code=str(e));dump(out/'report.json',report);return report
    critic=await cached_structured(out/'critic','Check generic memory-management rules: no task answers, benchmark identities, or mandatory finish/continuation overrides. Preserve user authority.',procedures,CRITIC,controller.wait_gateway)
    if not all(critic[k] for k in ('generic','no_task_answers','preserves_user_authority')):
        report=dict(status='no_accepted_update',promotions=0,reason='critic_rejected');dump(out/'report.json',report);return report
    dump(out/'candidate-policy.json',candidate);dump(out/'candidate-procedures.json',procedures)
    rows=await evaluate_jobs(jobs,out/'probes',candidate,budget,controller)
    effect=select(rows,len(jobs));dump(out/'selection.json',effect)
    report=dict(status='candidate_ready_for_test' if effect['accepted'] else 'no_accepted_update',promotions=int(effect['accepted']),effect=effect,
                cached_parents_not_new_samples=True,heldout_success_not_yet_established=True)
    dump(out/'report.json',report);return report
