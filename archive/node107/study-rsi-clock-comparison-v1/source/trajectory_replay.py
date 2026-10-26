"""Rebuild memory from first public event. Score later independent decisions.
Controlled replay, not physical execution. Stop on divergence, never borrow
feedback for an action that this replay did not choose. Every U is recomputed.
"""
import asyncio,json,hashlib
from pathlib import Path
from replay import dump
from durable_queue import read
from runtime_config import usage_totals

def lines(p):return [json.loads(x) for x in Path(p).read_text().splitlines()] if Path(p).exists() else []
def fixture(source):
    source=Path(source);r=read(source/'result.json');events=lines(source/'received-events.jsonl')
    if r['status'] not in ('success','decision_failure'):raise ValueError('not_decision_evidence')
    if not all(x['result']['success'] for x in r['physical_executions']):raise ValueError('physical_failure')
    requested=[x for x in events if x['decision_requested']]
    if len(requested)!=len(r['decisions']):raise ValueError('source_alignment')
    decisions={e['id']:d for e,d in zip(requested,r['decisions'])}
    targets=[e['id'] for e,d in zip(requested,r['decisions']) if d['checkpoint'] or not d['correct']]
    if not targets:raise ValueError('no_testable_decision')
    archives=[]
    for p in source.glob('rollover-*/audit.json'):
        a=read(p)
        if a['success']:archives.append(a['last_received_event'])
    return dict(source=str(source),sha256=hashlib.sha256((source/'result.json').read_bytes()).hexdigest(),
        events=events,decisions=decisions,targets=targets,archives=sorted(archives),
        scope='public history rebuild, teacher-forced prefix, autonomous suffix decisions, no physical claim')

async def evaluate(f,out,policy,budget):
    from replay_clock import installed
    with installed():
        return await _evaluate(f,out,policy,budget)

async def _evaluate(f,out,policy,budget):
    from twenty_agent import TwentyAgent
    out=Path(out)
    if (out/'result.json').exists():return read(out/'result.json')
    if out.exists():
        # An interrupted replay is retained as invalid; never reset calls/retry until success.
        r=dict(source=f['source'],status='technical_failure',correct=0,planned=len(f['targets']),answered=0,
               error_code='interrupted_replay',model_cost_complete=False)
        dump(out/'result.json',r);return r
    out.mkdir(parents=True);dump(out/'policy.json',policy)
    dump(out/'fixture-audit.json',{k:v for k,v in f.items() if k not in ('events','decisions')})
    phase='initializing';a=None;r=dict(source=f['source'],status='running',correct=0,answered=0,planned=len(f['targets']),decisions=[])
    first,last=min(f['targets']),max(f['targets'])
    try:
        a=TwentyAgent('memrsi',out,out/'policy.json',budget)
        for e in f['events']:
            eid=e['id'];phase='event'
            from replay_clock import set_event
            set_event(eid)
            if eid>last:break
            d=f['decisions'].get(eid) or f['decisions'].get(str(eid))
            if eid<first:
                if d:await a.replay_observe(e['text'],{'skill':d['skill'],'reason':'Recorded source action, not an answer hint.'})
                else:await a.observe_only(e['text'])
            elif d:
                phase='decision';c=await a.turn(e['text'],decision=True);ok=c['skill']==d['expected_private']
                if eid in f['targets']:r['answered']+=1;r['correct']+=int(ok)
                r['decisions'].append(dict(event=eid,skill=c['skill'],correct=ok))
                if not ok:
                    r['status']='decision_failure';break
                if c['skill']!=d['skill']:
                    # Corrected a source error; its counterfactual future is unavailable.
                    r['status']='source_error_corrected';break
            else:await a.observe_only(e['text'])
            if eid in f['archives']:
                phase='archive';await a.rollover()
        if r['status']=='running':r['status']='completed'
    except Exception as ex:
        code=str(ex)
        safe={'provider_error','active_context_budget_exceeded','persistent_memory_budget_exhausted','native_session_archival_failed','action_protocol_failure','guidance_protocol_failure','optimizer_call_budget','agent_call_budget_exhausted','generation_output_limit','delta_update_protocol_failure','delta_memory_schema'}
        known=code in safe
        technical=code=='provider_error' or type(ex).__name__ in ('APIConnectionError','APITimeoutError','ConnectionError','TimeoutError')
        r.update(status='technical_failure' if technical else 'agent_failure',error_type=type(ex).__name__,error_code=code if known else 'unclassified_exception',failure_phase=phase)
        if not known and not technical:r['status']='unclassified_failure'
        if code=='optimizer_call_budget':r['status']='learning_budget_exhausted'
    finally:
        if a:await a.close()
        r.update(usage_totals(out));dump(out/'result.json',r)
    return r
