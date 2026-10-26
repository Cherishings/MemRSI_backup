"""Four feedback rounds over 20 new full episodes, never reads held-out rows."""
import asyncio,copy,json
from pathlib import Path
from durable_queue import read
from replay import dump
from stream_design import development_rows,SEED_PROCEDURES,SCHEMA,compile_procedures
from stream_replay import fixture,paired,select,lines
from structured_feedback import structured,CRITIC,StructuredFailure
from memory_policy import digest
from feedback_learning import screen_generic

MAX_OPTIMIZER_CALLS=6000

def budget_check(out):
    n=sum(read(p,{}).get('calls',0) for p in Path(out).rglob('calls.json') if 'physical' not in p.parts)
    if n>=MAX_OPTIMIZER_CALLS:raise RuntimeError('optimizer_call_budget')
    return n

def feedback(rows):
    result=[]
    for row in rows:
        p=Path(row['output']);ev=lines(p/'received-events.jsonl');guides=lines(p/'guidance-events.jsonl')
        snaps=sorted(p.glob('rollover-*/memory-after.md'),key=lambda x:int(x.parent.name.split('-')[-1]))
        result.append({'id':row['trial_id'],'status':row['status'],'completed_sessions':row.get('sessions_completed'),
            'decisions':row.get('decisions',[])[-3:],'recent_public_events':[dict(id=x['id'],text=x['text'][:900],decision_requested=x['decision_requested'],truncated=len(x['text'])>900) for x in ev[-4:]],
            'long_memory_excerpt':snaps[-1].read_text()[:2200] if snaps else '',
            'guidance_excerpt':str(guides[-1].get('generated'))[:900] if guides else '',
            'physical_successes':sum(x['result']['success'] for x in row.get('physical_executions',[])),
            'excerpt_not_full_trajectory':True})
    return result

def replay_sources(rows):
    # Include successes AND failures; deterministic recent samples, no search for a gain.
    good=[];bad=[]
    for r in reversed(rows):
        try:fixture(r['output'])
        except (ValueError,KeyError,FileNotFoundError):continue
        (good if r['status']=='success' else bad).append(r['output'])
    return good[:3]+bad[:3]

async def cached_structured(path,system,data,schema,wait_gateway):
    path=Path(path)
    if (path/'value.json').exists():return read(path/'value.json')
    # Strictly reuse prior successful submissions. Partial requests are retained;
    # no unbounded regeneration on restart.
    if path.exists():raise RuntimeError('interrupted_proposal_requires_audit')
    await asyncio.to_thread(wait_gateway)
    return await structured(path,system,data,schema)

async def run(out,experiment,budget):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'report.json').exists():return read(out/'report.json')
    from model_provider import LEARNING_LEDGER
    LEARNING_LEDGER.set(out/'learning-call-ledger.json')
    current=copy.deepcopy(SEED_PROCEDURES);parent=compile_procedures(current);promotions=0;all_rows=[];rounds=[]
    dump(out/'seed-procedures.json',current);dump(out/'snapshots/after-00.json',parent)
    dev_rows=[dict(r,gpu=experiment.gpus[i % len(experiment.gpus)]) for i,r in enumerate(development_rows())]
    manifest={'physical_development':dev_rows,'updates_after':[5,10,15,20],
        'source_scope':'new development physical runs only','test_feedback_used':False,
        'rule_space':'complete bounded G/U procedure texts; no trainable weights',
        'proposal_per_round':1,'paired_replay_repetitions':2,'replay_source_limit':6,
        'max_optimizer_calls':MAX_OPTIMIZER_CALLS,'rule_promotion':'paired replay gain/no regression/cost <=1.5x',
        'physical_recursive_gain':'not assumed; next development batch measures transfer',
        'seed_is_original_manual_procedures':True}
    old=read(out/'manifest.json')
    if old is not None and old!=manifest:raise RuntimeError('learning_manifest_changed')
    dump(out/'manifest.json',manifest)
    for idx in range(4):
        folder=out/f'round-{idx}';folder.mkdir(exist_ok=True)
        dump(folder/'parent-policy.json',parent)
        experiment.state('learning_physical_batch',round=idx,promotions=promotions)
        rows=await asyncio.to_thread(experiment.batch,dev_rows[idx*5:(idx+1)*5],
              {'memrsi':folder/'parent-policy.json'},folder/'physical')
        all_rows.extend(rows)
        existing=read(folder/'decision.json')
        if existing is not None:
            if existing['parent_hash']!=digest(parent):raise RuntimeError('learning_parent_changed')
            if existing['accepted']:
                current=read(folder/'accepted-procedures.json');parent=compile_procedures(current);promotions+=1
            dump(out/f'snapshots/after-{(idx+1)*5:02d}.json',parent)
            rounds.append(existing);continue
        decision={'round':idx,'parent_hash':digest(parent),'accepted':False,
                  'physical_statuses':[r['status'] for r in rows]}
        sources=replay_sources(all_rows)
        dump(folder/'learning-evidence.json',feedback(rows));dump(folder/'replay-sources.json',sources)
        try:
            budget_check(out)
            if not sources:decision['reason']='no_usable_development_trajectory'
            else:
                experiment.state('learning_rule_proposal',round=idx,promotions=promotions)
                proposal=await cached_structured(folder/'proposal',
                    'Improve the long/short memory interface from actual development experience. '
                    'Long memory guides current short-term work; short-term execution feedback updates durable memory. '
                    'Return complete replacement guidance and update procedures, not task answers. '
                    'You may improve what is retained/compressed, how evidence changes progress, and how relevant evidence is read. '
                    'Use failures and successes; preserve what worked. Explain the diagnosed information loss and predicted change in rationale. '
                    'Do not encode objects, table IDs, tools, action orders, dates, test labels or counts. '
                    'Do not force continuation/finish or override users. No access to evaluation files. '
                    'Guidance selects source fragment IDs only; Update governs the original native archival writes. '
                    'Each procedure must fit 1600 characters. Absent genuine evidence, preserve the parent.',
                    {'parent':current,'current_batch_feedback':feedback(rows),'prior_rounds':rounds},SCHEMA,experiment.wait_gateway)
                candidate=compile_procedures(proposal);screen_generic(candidate)
                critic=await cached_structured(folder/'critic',
                    'Check whether these general memory procedures avoid concrete task answers and preserve user authority. '
                    'Reject hard rules forcing finish/continuation regardless of user intent.',proposal,CRITIC,experiment.wait_gateway)
                if not all(critic[k] is True for k in ('generic','no_task_answers','preserves_user_authority')):
                    decision['reason']='genericity_rejected'
                elif digest(candidate)==digest(parent):decision['reason']='unchanged'
                else:
                    dump(folder/'candidate-policy.json',candidate)
                    experiment.state('learning_rebuild_replay',round=idx,promotions=promotions)
                    measurements=await paired(sources,folder/'replay',parent,candidate,budget,experiment.wait_gateway)
                    decision.update(select(measurements));budget_check(out)
                    if decision['accepted']:
                        current={k:proposal[k] for k in ('guidance','update')};parent=candidate;promotions+=1
                        dump(folder/'accepted-procedures.json',current)
        except (RuntimeError,ValueError) as ex:
            # Reject an invalid/budget-limited update; continue future valid physical batches.
            # Never pass infrastructure failure to the actor as a memory-learning label.
            decision.update(accepted=False,reason='update_not_validated',error_type=type(ex).__name__)
            if isinstance(ex,StructuredFailure) or str(ex)=='optimizer_context_cannot_fit_preserved_evidence':
                decision['error_code']=str(ex)
                dump(folder/'decision-blocked.json',decision)
                raise  # Never silently mark an unexecuted update round as finished.
            if experiment.stop.is_set():raise RuntimeError('queue_cancelled')
        decision.update(selected_hash=digest(parent),promotions_so_far=promotions)
        dump(folder/'decision.json',decision);rounds.append(decision)
        dump(out/f'snapshots/after-{(idx+1)*5:02d}.json',parent)
        dump(out/'progress.json',dict(completed_development=(idx+1)*5,promotions=promotions))
    dump(out/'frozen-policy.json',parent)
    report=dict(status='completed',development_completed=len(all_rows),promotions=promotions,
        frozen_sha256=digest(parent),rounds=rounds,selection='last accepted policy; seed if no accepted update',
        heldout_results_read=False,recursive_physical_gain_proven=False)
    dump(out/'report.json',report);return report
