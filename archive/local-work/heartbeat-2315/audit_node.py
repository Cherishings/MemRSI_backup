import json,hashlib
from pathlib import Path
r=Path('/data/songziying/paos-libero-20261023/study-feedback-v2-physical-pilot')
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
reg=read(r/'selection-registration.json');schedule=read(r/'development-schedule.json')
assert len(schedule)==8 and read(r/'queue-status.json')['phase']=='development_complete'
rows=[]
for job in schedule:
 p=Path(job['output']);v=read(p/'result.json');arm=job['arm'];policy=r/'policies'/f'{arm}.json'
 assert sha(policy)==reg['policy_file_hashes'][arm]
 if arm!='native':assert read(p/'applied-memory-policy.json')==read(policy)
 calls=read(p/'calls.json'); traces=sum(1 for line in (p/'model-trace.jsonl').open() if line.strip())
 assert calls['calls']>0 and traces>0
 success=v['status']=='success'
 if success:
  assert len(v['physical_executions'])==20 and all(x['result']['success'] for x in v['physical_executions'])
  assert all(x['result']['after']['policy_calls']>0 for x in v['physical_executions'])
  assert len(v['rollovers'])==19 and all(x['success'] for x in v['rollovers'])
  assert v['correct_checkpoints']==v['planned_checkpoints']==7
  assert v['decisions'][-1]['skill']=='finish' and v['decisions'][-1]['correct']
  assert all(x['correct'] for x in v['decisions'])
  assert v['physical_executions'][-1]['result']['native_task_complete']
 classification=v['status']
 if reg['node']=='107' and arm=='g_only':
  assert (r/'continuation-g_only-1914.json').exists()
  classification='method_archive_output_limit'
 rows.append({'arm':arm,'result_path':str(p/'result.json'),'result_sha256':sha(p/'result.json'),'raw_status':v['status'],'classification':classification,'verified_complete_success':success,'correct_checkpoints':v['correct_checkpoints'],'logical_calls':calls,'model_trace_records':traces,'policy_file_sha256':sha(policy),'applied_policy_verified':arm!='native','model_input_tokens':v['model_input_tokens'],'model_output_tokens':v['model_output_tokens'],'cost_complete':v['model_cost_complete'],'unknown_requests':v['model_cost_unknown_requests']})
print(json.dumps({'node':reg['node'],'selection_registration_sha256':sha(r/'selection-registration.json'),'rows':rows}))
