"""Actual request/exposure gate; never uses task success as acceptance."""
import json
from pathlib import Path
from advisor import MODES

def lines(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def inspect(out,jobs):
 rows=[];issues=[]
 for j in jobs:
  case=Path(out)/j['key'];a=case/'attempt-01/agent';arm=j['arm'];mode=arm.split('_')[0]
  if not (case/'result.json').exists():return {'state':'waiting','rows':rows,'issues':[]}
  contract=json.loads((a/'advisor-contract.json').read_text());traces=[v for p in a.rglob('model-trace.jsonl') for v in lines(p)]
  calls=inject=archive=custom=0
  for t in traces:
   req=t.get('request',{});names={v.get('function',{}).get('name') for v in req.get('tools',[]) or []};messages=req.get('messages',[]);txt=json.dumps(messages)
   guide=bool(names & {'report_advice','select_memory_evidence'});calls+=guide
   inject+=('# Nonbinding decision advice' in txt or '# Selected memory evidence' in txt)
   if guide and mode in MODES:
    if names!={'report_advice'} or not messages or messages[0].get('content')!=MODES[mode]:issues.append(arm+':wrong_advisor_request')
    try: data=json.loads(messages[1]['content']);assert data['execution_api'] and 'current' in data['evidence']
    except Exception:issues.append(arm+':missing_public_input')
   is_u=names in ({'save_memory'},{'pack_storage'});archive+=is_u;custom+=is_u and 'Update procedure for the long/short memory interface.' in txt
  events=lines(a/'advisor-prototype.jsonl');exp=[v for p in a.rglob('gu-exposure.jsonl') for v in lines(p)]
  nonempty=sum(x.get('native_short_messages',0)>0 for x in events+exp)
  correlations=lines(a/'receipt-correlations.jsonl')
  if contract['arm']!=arm or not contract['same_U']:issues.append(arm+':contract_mismatch')
  if mode=='off' and (calls or inject or events or exp):issues.append(arm+':guidance_not_off')
  if mode!='off' and (not calls or not inject or not nonempty):issues.append(arm+':exposure_unverified')
  if mode in MODES and (not events or any(x['mode']!=mode for x in events)):issues.append(arm+':mode_unverified')
  if not archive or custom!=archive:issues.append(arm+':U_unverified')
  if not correlations:issues.append(arm+':receipts_unverified')
  rows.append({'arm':arm,'guidance_requests':calls,'actor_injections':inject,'archive_requests':archive,'custom_U_requests':custom,'nonempty_S':nonempty,'correlations':len(correlations)})
 return {'state':'blocked' if issues else 'passed','issues':issues,'rows':rows,'performance_used_as_gate':False}
