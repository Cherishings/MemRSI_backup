from pathlib import Path
import json,hashlib,collections
base=Path('backups/paos-rescue-20261026/node107');remote='/data/songziying/paos-libero-20261023/'
r=base/'study-rsi-clock-comparison-v1';rows=json.loads((r/'learning/training/rows.json').read_text());reg=json.loads((r/'comparison-registration.json').read_text());report=json.loads((r/'learning/report.json').read_text())
assert len(rows)==24
assert len({(x['source_id'],x['repeat'],x['arm']) for x in rows})==24
summ={}; evidence=[]
for arm in reg['arms']:
 armrows=[x for x in rows if x['arm']==arm];assert len(armrows)==8
 assert {(x['source_id'],x['repeat']) for x in armrows}=={(s['id'],i) for s in reg['sources'] for i in [0,1]}
 for x in armrows:
  assert x['policy_sha256']==reg['policy_hashes'][arm]
  p=base/x['output'].removeprefix(remote);z=json.loads((p/'result.json').read_text());assert z['policy_sha256']==x['policy_sha256']
  trace=p/'model-trace.jsonl';assert trace.exists() and trace.stat().st_size>0 and x['logical_calls']>0
  evidence.append({'output':x['output'],'result_sha256':hashlib.sha256((p/'result.json').read_bytes()).hexdigest(),'trace_sha256':hashlib.sha256(trace.read_bytes()).hexdigest()})
 summ[arm]={'correct':sum(x['correct'] for x in armrows),'planned':sum(x['planned'] for x in armrows),'completed':sum(x['status']=='completed' for x in armrows),'logical_calls':sum(x['logical_calls'] for x in armrows),'input_tokens_lower_bound':sum(x.get('model_input_tokens',0) for x in armrows),'output_tokens_lower_bound':sum(x.get('model_output_tokens',0) for x in armrows),'cost_incomplete_cases':sum(not x['model_cost_complete'] for x in armrows),'unknown_requests':sum(x.get('model_cost_unknown_requests',0) for x in armrows),'statuses':dict(collections.Counter(x['status'] for x in armrows))}
assert sum(x['logical_calls'] for x in summ.values())==5056-4565
out={'rows':24,'unique_paired_rows':24,'policy_bindings_and_real_calls_verified':True,'report_sha256':hashlib.sha256((r/'learning/report.json').read_bytes()).hexdigest(),'summary':summ,'selected_for_pilot':report['selected_for_pilot'],'physical_success_claimed':False,'old_joint_previous_reserved_failure_retained':True,'no_new_proposal_replay_or_physical_run':True,'next_stage_constraint':'Server deadline unknown; full eight-arm physical pilot availability cannot yet be assessed.','evidence':evidence}
Path('work/heartbeat-clock-complete/completion-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(summ))
