"""Untouched history groups; full-history reconstruction, never proposer feedback."""
import asyncio
from pathlib import Path
from durable_queue import read
from replay import dump
from stream_replay import fixture,evaluate,lines

async def replay_one(f,out,policy,budget,wait_gateway):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'result.json').exists():return read(out/'result.json')
    attempts=[]
    for i in range(1,4):
        await asyncio.to_thread(wait_gateway)
        path=out/f'attempt-{i:02d}';r=await evaluate(f,path,policy,budget);r=dict(r,calls=read(path/'calls.json',{}).get('calls',0));attempts.append(r)
        if r['status']!='invalid' or not lines(path/'model-errors.jsonl'):break
    result=dict(r,attempts=len(attempts),all_attempt_calls=sum(x['calls'] for x in attempts),cost_known=all(x.get('model_cost_complete') for x in attempts),
                all_attempt_tokens=sum(x.get('model_input_tokens',0)+x.get('model_output_tokens',0) for x in attempts))
    dump(out/'result.json',result);return result

def gate(rows,planned_sources):
    groups={}
    for r in rows:groups.setdefault((r['case'],r['repeat']),{})[r['policy']]=r
    good=[x for x in groups.values() if set(x)=={'parent','candidate'} and all(x[k]['status']!='invalid' for k in x)]
    matched=all(x['parent']['planned']==x['candidate']['planned'] for x in good)
    a=sum(x['parent']['correct'] for x in good);b=sum(x['candidate']['correct'] for x in good)
    planned=sum(x['parent']['planned'] for x in good)
    tok={k:sum(r.get('all_attempt_tokens',0) for r in rows if r['policy']==k) for k in ('parent','candidate')}
    calls={k:sum(r.get('all_attempt_calls',0) for r in rows if r['policy']==k) for k in ('parent','candidate')}
    complete=len(good)==planned_sources*2 and planned_sources>=2 and matched
    accepted=complete and b>=a and calls['candidate']<=1.5*max(1,calls['parent'])
    return {'passed':accepted,'planned_sources':planned_sources,'planned_pairs':planned_sources*2,'valid_pairs':len(good),
            'parent_correct':a,'candidate_correct':b,'planned_checkpoints_each':planned,'cost_tokens':tok,'logical_calls':calls,'token_usage_complete':all(r.get('cost_known') for r in rows),
            'scope':'one sealed full-history replay validation; not physical success or a statistical generalization claim'}

async def run(source_rows,out,parent,candidate,budget,wait_gateway):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'report.json').exists():return read(out/'report.json')
    fs=[];excluded=[]
    for row in source_rows:
        try:fs.append((row['trial_id'],fixture(row['output'])))
        except (ValueError,KeyError,FileNotFoundError) as ex:excluded.append({'id':row['trial_id'],'source_status':row['status'],'reason':type(ex).__name__})
    dump(out/'source-audit.json',{'planned_source_cases':4,'eligible':len(fs),'excluded':excluded,'ids':[k for k,f in fs]})
    rows=[]
    for i,(case,f) in enumerate(fs):
        for rep in range(2):
            order=[('parent',parent),('candidate',candidate)]
            if (i+rep)%2:order.reverse()
            results=await asyncio.gather(*(replay_one(f,out/f'{case}-r{rep}-{k}',p,budget,wait_gateway) for k,p in order))
            rows.extend(dict(r,case=case,repeat=rep,policy=k) for r,(k,_) in zip(results,order));dump(out/'rows.json',rows)
    report=gate(rows,len(fs));dump(out/'report.json',report);return report
