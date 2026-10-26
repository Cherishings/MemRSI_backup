import json, hashlib
from pathlib import Path
B=Path('/data/songziying/paos-libero-20261023/study-rsi-typed-process-v1')
P=B/'learning/training/replays'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text())
r=P/'020-joint-r1/rollover-13'
before=(r/'memory-before.md').read_text(); after=(r/'memory-after.md').read_text(); msgs=read(r/'messages-before.json')
for label in ['A (E2–3)','B (E6–7)','C (E11–12)']:
 assert 'pudding pending' in next(s for s in before.splitlines() if label in s)
 assert 'discharged' in next(s for s in after.splitlines() if label in s)
receipts=[m['content'] for m in msgs if m.get('role')=='user' and 'Execution feedback:' in m.get('content','')]
assert len(receipts)==1 and '"skill": "serve_E"' in receipts[0]
trace=P/'017-joint-r0/model-trace.jsonl'
x=json.loads(trace.read_text().splitlines()[-1]); resp=x['response']
# Trace stores the original chat response.
message=resp['choices'][0]['message'] if 'choices' in resp else resp
calls=message['tool_calls']; assert len(calls)==1
args=calls[0]['arguments']; extra=set(args)-{'recommendation','basis_ids','uncertainty'}
assert len(extra)==1
assert set(args['basis_ids']) <= {'current','memory','history'}
limits=[]
for f in sorted(P.glob('*/model-errors.jsonl')):
 for line in f.read_text().splitlines():
  e=json.loads(line)
  if e.get('code')=='generation_output_limit':
   limits.append({'replay':f.parent.name,'file_sha256':sha(f),**e})
assert len(limits)==8
assert all(e['partial_items'][0]['name']=='report_advice' and e['retry_same_input']==False for e in limits)
files=[r/n for n in ['memory-before.md','memory-after.md','messages-before.json','audit.json']]+[trace,B/'learning/training/rows.json',B/'learning/report.json']
out={'scope':'training-only, zero model calls; no outcome reclassification','study':str(B),'evidence_sha256':{str(p.relative_to(B)):sha(p) for p in files},'memory_transition':{'replay':'020-joint-r1','rollover':13,'before':before,'after':after,'new_receipts':receipts,'finding':'Only E has a new completion receipt, but A/B/C change from pending to discharged. This is an observed erroneous memory transition, not proof the learned text caused it.'},'protocol_failure':{'replay':'017-joint-r0','function':calls[0]['name'],'extra_field_count':len(extra),'extra_field_sha256':[hashlib.sha256(k.encode()).hexdigest() for k in extra],'basis_ids':args['basis_ids'],'finding':'Unexpected extra field, not invalid citation; original rejection retained.'},'output_limits':limits,'limits':'No validation, physical pilot or final-test trajectories used. No new candidate or retry. Source-error-corrected is not full completion.'}
print(json.dumps(out,ensure_ascii=False,indent=2))
