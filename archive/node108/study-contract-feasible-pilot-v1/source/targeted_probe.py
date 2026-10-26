"""Matched one-archive interventions; bounded transport retries, all costs retained."""
import asyncio,copy,json
from pathlib import Path
from durable_queue import read
from feedback_learning import lines
from replay import dump
from runtime_config import usage_totals
from memory_budget import write_pair

async def attempt(f,out,policy,budget):
    from twenty_agent import TwentyAgent
    out=Path(out)
    if (out/'result.json').exists():return read(out/'result.json')
    if out.exists():
        r={'fixture':f['id'],'status':'technical_failure','correct':False,'reason':'interrupted_attempt','calls':read(out/'calls.json',{}).get('calls',0)}
        r.update(usage_totals(out));dump(out/'result.json',r);return r
    out.mkdir(parents=True);dump(out/'policy.json',policy)
    a=None;r={'fixture':f['id'],'status':'running','correct':False,'scope':'single_archive_window_no_physical_claim'}
    try:
        a=TwentyAgent('memrsi',out,out/'policy.json',budget);a.event_id=f['last_archived_event']
        write_pair(a.store,(f['memory_before'],f['history_before']))
        session=a.loop.sessions.get_or_create(a.session_key);session.messages=copy.deepcopy(f['archive_messages']);a.loop.sessions.save(session)
        await a.rollover()
        for e in f['suffix']:
            if e['choice']:await a.replay_observe(e['text'],e['choice'])
            else:await a.observe_only(e['text'])
        if a.event_id+1!=f['current_event_id']:raise ValueError('event_alignment')
        choice=await a.turn(f['request'],decision=True)
        r.update(status='answered',correct=choice['skill']==f['expected_private'],choice=choice)
    except Exception as ex:
        transport=lines(out/'model-errors.jsonl')
        technical=(str(ex)=='provider_error' and bool(transport)) or type(ex).__name__ in ('APIConnectionError','APITimeoutError','ConnectionError','TimeoutError')
        r.update(status='technical_failure' if technical else 'agent_failure',error_type=type(ex).__name__,
                 reason=str(ex) if str(ex) in ('active_context_budget_exceeded','persistent_memory_budget_exhausted','action_protocol_failure','guidance_protocol_failure','event_alignment','native_session_archival_failed') else 'inspect_structured_evidence')
    finally:
        if a:await a.close();r['calls']=a.provider.calls
        r.update(usage_totals(out));dump(out/'result.json',r)
    return r

async def probe(f,out,policy,budget,wait_gateway):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'result.json').exists():return read(out/'result.json')
    attempts=[]
    for i in range(1,4):
        await asyncio.to_thread(wait_gateway)
        r=await attempt(f,out/f'attempt-{i:02d}',policy,budget);attempts.append(r)
        if r['status']!='technical_failure':break
    r=dict(r,attempts=len(attempts),all_attempt_calls=sum(x.get('calls',0) for x in attempts),all_attempt_cost_tokens=sum(x.get('model_input_tokens',0)+x.get('model_output_tokens',0) for x in attempts),
           all_costs_known=all(x.get('model_cost_complete',False) for x in attempts),
           original_attempts_preserved=True)
    dump(out/'result.json',r);return r

async def paired(fs,out,parent,candidate,budget,wait_gateway,repetitions=3):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    manifest={'fixtures':[{'id':f['id'],'source':f['source'],'source_sha256':f['source_sha256']} for f in fs],
              'parent':parent,'candidate':candidate,'repetitions':repetitions,'attempt_cap':3}
    old=read(out/'manifest.json')
    if old is not None and old!=manifest:raise RuntimeError('probe_manifest_changed')
    dump(out/'manifest.json',manifest);rows=[]
    # One pair at a time, two concurrent requests maximum, matching shared gateway.
    for i,f in enumerate(fs):
        for rep in range(repetitions):
            order=[('parent',parent),('candidate',candidate)]
            if (i+rep)%2:order.reverse()
            got=await asyncio.gather(*(probe(f,out/f"{f['id']}-r{rep}-{name}",policy,budget,wait_gateway) for name,policy in order))
            rows.extend(dict(r,policy=name,repeat=rep) for r,(name,_) in zip(got,order))
            dump(out/'rows.json',rows)
    return rows

def summarize(rows):
    groups={}
    for r in rows:groups.setdefault((r['fixture'],r['repeat']),{})[r['policy']]=r
    valid=[x for x in groups.values() if set(x)=={'parent','candidate'} and all(x[k]['status']!='technical_failure' for k in x)]
    a=sum(bool(x['parent']['correct']) for x in valid);b=sum(bool(x['candidate']['correct']) for x in valid)
    cases={}
    for (case,_),x in groups.items():
        if x in valid:
            v=cases.setdefault(case,[0,0,0]);v[0]+=int(x['parent']['correct']);v[1]+=int(x['candidate']['correct']);v[2]+=1
    persistent_regressions=[k for k,(a,b,n) in cases.items() if a==n and b==0]
    tok={k:sum(r.get('all_attempt_cost_tokens',0) for r in rows if r['policy']==k) for k in ('parent','candidate')}
    calls={k:sum(r.get('all_attempt_calls',0) for r in rows if r['policy']==k) for k in ('parent','candidate')}
    complete=bool(rows) and all(r.get('all_costs_known',False) for r in rows)
    n=len(valid)
    return {'planned_pairs':len(groups),'valid_pairs':n,'parent_correct':a,'candidate_correct':b,
      'gain':b-a,'gain_fraction':(b-a)/n if n else None,'persistent_regressions':persistent_regressions,
      'per_case':cases,'cost_complete':complete,'cost_tokens':tok,
      'logical_calls':calls,'cost_metric':'logical requests including all technical attempts; token usage reported separately',
      'cost_ok':calls['candidate']<=1.5*max(1,calls['parent'])}

def select(rows):
    s=summarize(rows)
    # v1.8 exploratory promotion: any positive aggregate gain may advance.
    # Old pilot reuse is disclosed; only sealed validation and heldout assess transfer.
    s['accepted']=bool(s['valid_pairs'] and s['valid_pairs']==s['planned_pairs'] and
        s['gain']>0 and not s['persistent_regressions'] and s['cost_ok'])
    return s
