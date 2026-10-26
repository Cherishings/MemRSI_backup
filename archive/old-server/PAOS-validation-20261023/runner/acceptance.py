"""Information-flow acceptance; no task-success thresholds or hidden labels."""
import json
from pathlib import Path
def lines(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def inspect(out,jobs):
 rows=[];issues=[]
 for j in jobs:
  case=Path(out)/j['key'];a=case/'attempt-01/agent'
  if not (case/'result.json').exists():return {'state':'waiting','rows':rows,'issues':[]}
  c=json.loads((a/'gu-contract.json').read_text());g=j['arm'].startswith('g1');u=j['arm'].endswith('u1')
  traces=[v for p in a.rglob('model-trace.jsonl') for v in lines(p)];grequests=0;ginjections=0;archive=0;uused=0
  for t in traces:
   req=t.get('request',{});names={x.get('function',{}).get('name') for x in req.get('tools',[]) or []};txt=json.dumps(req.get('messages',[]))
   grequests+='select_memory_evidence' in names;ginjections+='# Selected memory evidence' in txt
   is_u=names in ({'save_memory'},{'pack_storage'});archive+=is_u;uused+=is_u and 'Update procedure for the long/short memory interface.' in txt
  expo=[v for p in a.rglob('gu-exposure.jsonl') for v in lines(p)]
  row={'arm':j['arm'],'guidance_requests':grequests,'guidance_injections':ginjections,'native_archive_requests':archive,'custom_update_requests':uused,'nonempty_guidance_S_events':sum(x['guidance_short_messages']>0 for x in expo),'contract':c};rows.append(row)
  if c['guidance_enabled']!=g or c['update_enabled']!=u:issues.append(j['arm']+':constructor_contract')
  if g and (not grequests or not ginjections or not row['nonempty_guidance_S_events']):issues.append(j['arm']+':guidance_exposure_unverified')
  if not g and (grequests or ginjections or expo):issues.append(j['arm']+':guidance_not_disabled')
  if not archive:issues.append(j['arm']+':archive_exposure_unverified')
  if u and uused!=archive:issues.append(j['arm']+':update_missing')
  if not u and uused:issues.append(j['arm']+':native_update_not_native')
 return {'state':'blocked' if issues else 'passed','issues':issues,'rows':rows,'performance_used_as_gate':False}
