"""Replay the exact recorded failure's L/S state with corrected tool/receipt semantics.
No archive reconstruction or autonomous-episode claim. Original evidence untouched.
"""
import argparse,asyncio,copy,json,re
from pathlib import Path
from agent_adapter import Agent
from execution_contract import receipt
from memory_policy import BASE
from replay import dump

async def main(root,out):
    root,out=Path(root),Path(out);out.mkdir(exist_ok=False,parents=True)
    policy=out/'policy.json';dump(policy,BASE);rows=[]
    for name in ['case-00-rep0','case-02-rep0','case-07-rep0']:
        d=root/name;r=json.loads((d/'result.json').read_text());source=json.loads((Path(r['source'])/'result.json').read_text())
        traces=[json.loads(s) for s in (d/'model-trace.jsonl').read_text().splitlines()]
        guides=[t for t in traces if any(x.get('function',{}).get('name')=='submit_guidance' for x in t['request'].get('tools',[]))]
        if not guides:raise RuntimeError('missing_guidance_input')
        payload=json.loads(guides[-1]['request']['messages'][-1]['content'])
        # Determine evaluation label separately. Never insert it into Agent input.
        wrong=[x for x in r['decisions'] if not x['correct']]
        expected=wrong[-1]['expected'] if wrong else source['decisions'][-1]['expected']
        messages=copy.deepcopy(payload['short_working_memory']);enriched=0
        for m in messages:
            content=m.get('content')
            if m.get('role')!='user' or not isinstance(content,str) or 'Execution feedback: ' not in content:continue
            prefix,raw=content.split('Execution feedback: ',1)
            feedback=json.loads(raw)
            matches=[x for x in source['physical_executions'] if x['skill']==feedback['skill'] and x['result']['after']['scene_observation']==feedback['scene_observation']]
            if len(matches)!=1:raise RuntimeError('snapshot_receipt_alignment')
            new=receipt(feedback['skill'],matches[0]['result'])
            if 'work_order_id' in feedback:new['work_order_id']=feedback['work_order_id']
            m['content']=prefix+'Execution feedback: '+json.dumps(new);enriched+=1
        a=Agent('memrsi',out/name,policy)
        try:
            mem=a.workspace/'memory/MEMORY.md';mem.parent.mkdir(exist_ok=True);mem.write_text(payload['long_mission_memory'])
            session=a.loop.sessions.get_or_create(a.session_key);session.messages=messages;a.loop.sessions.save(session)
            current=re.sub(r'^Event \d+: ','',payload['current_request'])
            choice=await a.turn(current,decision=True)
            row={'case':name,'expected_private':expected,'choice':choice,'correct':choice['skill']==expected,
                 'receipt_count':enriched,'format_repairs':a.provider.format_repairs,'calls':a.provider.calls}
        except Exception as exc:
            row={'case':name,'correct':False,'error_type':type(exc).__name__,'error_code':str(exc) if str(exc) in ['action_protocol_failure','guidance_protocol_failure','provider_error'] else 'inspect_structured_outputs'}
        finally:await a.close()
        rows.append(row);dump(out/'progress.json',{'terminal':len(rows),'planned':3,'rows':rows})
    dump(out/'report.json',{'all_correct':all(r['correct'] for r in rows),'rows':rows,'scope':'known-failure decision snapshots only; interface repair, not RSI learning or physical evidence'})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args();asyncio.run(main(a.source,a.output))
