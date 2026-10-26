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
    from twenty_agent import TwentyAgent
    out=Path(out)
    if (out/'result.json').exists():return read(out/'result.json')
    if out.exists():
        # An interrupted replay is retained as invalid; never reset calls/retry until success.
        r=dict(source=f['source'],status='invalid',correct=0,planned=len(f['targets']),answered=0,
               error_code='interrupted_replay',model_cost_complete=False)
        dump(out/'result.json',r);return r
    out.mkdir(parents=True);dump(out/'policy.json',policy)
    dump(out/'fixture-audit.json',{k:v for k,v in f.items() if k not in ('events','decisions')})
    a=None;r=dict(source=f['source'],status='running',correct=0,answered=0,planned=len(f['targets']),decisions=[])
    first,last=min(f['targets']),max(f['targets'])
    try:
        a=TwentyAgent('memrsi',out,out/'policy.json',budget)
        for e in f['events']:
            eid=e['id']
            if eid>last:break
            d=f['decisions'].get(eid) or f['decisions'].get(str(eid))
            if eid<first:
                if d:await a.replay_observe(e['text'],{'skill':d['skill'],'reason':'Recorded source action, not an answer hint.'})
                else:await a.observe_only(e['text'])
            elif d:
                c=await a.turn(e['text'],decision=True);ok=c['skill']==d['expected_private']
                if eid in f['targets']:r['answered']+=1;r['correct']+=int(ok)
                r['decisions'].append(dict(event=eid,skill=c['skill'],correct=ok))
                if not ok:
                    r['status']='decision_failure';break
                if c['skill']!=d['skill']:
                    # Corrected a source error; its counterfactual future is unavailable.
                    r['status']='source_error_corrected';break
            else:await a.observe_only(e['text'])
            if eid in f['archives']:await a.rollover()
        if r['status']=='running':r['status']='completed'
    except Exception as ex:
        r.update(status='invalid',error_type=type(ex).__name__)
    finally:
        if a:await a.close()
        r.update(usage_totals(out));dump(out/'result.json',r)
    return r

async def paired(sources,out,parent,candidate,budget,wait_gateway):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    fixtures=[fixture(s) for s in sources]
    frozen=[{k:f[k] for k in ('source','sha256')} for f in fixtures]
    old=read(out/'sources.json')
    if old is not None and old!=frozen:raise RuntimeError('replay_sources_changed')
    dump(out/'sources.json',frozen)
    rows=[]
    for i,f in enumerate(fixtures):
        for rep in range(2):
            for name,p in ([('parent',parent),('candidate',candidate)] if (i+rep)%2==0 else [('candidate',candidate),('parent',parent)]):
                await asyncio.to_thread(wait_gateway)
                r=await evaluate(f,out/f'case-{i}-rep-{rep}-{name}',p,budget)
                rows.append(dict(r,policy=name,case=i,repeat=rep))
    dump(out/'rows.json',rows)
    return rows

def select(rows):
    a={(r['case'],r['repeat']):r for r in rows if r['policy']=='parent'}
    b={(r['case'],r['repeat']):r for r in rows if r['policy']=='candidate'}
    if not a or a.keys()!=b.keys():return {'accepted':False,'reason':'unpaired'}
    if any(r['status']=='invalid' or not r.get('model_cost_complete') for r in rows):
        return {'accepted':False,'reason':'invalid_probe'}
    if any(a[k]['planned']!=b[k]['planned'] for k in a):raise ValueError('denominator_mismatch')
    gain=sum(b[k]['correct']-a[k]['correct'] for k in a)
    regressions=sum(b[k]['correct']<a[k]['correct'] for k in a)
    tok=lambda rs:sum(r.get('model_input_tokens',0)+r.get('model_output_tokens',0) for r in rs)
    cost_ok=tok(b.values())<=1.5*max(1,tok(a.values()))
    return {'accepted':gain>0 and not regressions and cost_ok,'correct_gain':gain,
        'regressed_repetitions':regressions,'cost_ok':cost_ok,'scope':'development replay only'}
