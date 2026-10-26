from pathlib import Path
s=Path('work/contract-validation/stage.py').read_text()
s=s.replace("old=b/'study-rsi-v4-sources';r=b/'study-contract-validation-v1'", "old=b/'study-contract-validation-v1';r=b/'study-contract-feasible-pilot-v1'")
s=s.replace("q=read(old/'queue-status.json');assert q['phase']=='development_complete'", "q=read(old/'queue-status.json');assert q.get('completed')==8\nassert len(list((old/'development').glob('*/*/result.json')))==8")
s=s.replace("used=set(m['all_histories']);fresh=[''.join(p) for p in itertools.permutations('ABCDE') if ''.join(p) not in used][:2]\nassert len(fresh)==2 and not set(fresh)&used", "used=set(m['all_histories']);fresh=['ABCDE','ABECD']")
s=s.replace('i{idx+2}', 'i2').replace("'init':idx+2", "'init':2")
s=s.replace("r.mkdir()", """r.mkdir()
summary=[]
for p in sorted((old/'development').glob('*/*/result.json')):
 d=read(p);summary.append({'arm':p.parent.name,'path':str(p),'sha256':sha(p),'status':d['status'],'classification':('method_archive_protocol_failure' if d.get('error_code')=='native_session_archival_failed' else d['status']),'correct_checkpoints':d.get('correct_checkpoints'),'sessions_completed':d.get('sessions_completed'),'model_cost_complete':d.get('model_cost_complete'),'input_tokens':d.get('model_input_tokens'),'output_tokens':d.get('model_output_tokens')})
(r/'previous-study-results.json').write_text(json.dumps(summary,indent=2))
(r/'physical-qualification.json').write_text(json.dumps({'selection_basis':'executor feasibility only, not method ranking','source_node':107,'source_result':'study-contract-validation-v1/development/hABCDE-v0-i2/think_u/result.json','verified':{'physical_successes':20,'rollovers':19,'checkpoints':7,'finish_correct':True,'bowl_executions':3,'bowl_policy_calls_each':22},'replacement':'same task, init2 for all arms on both distinct histories','old_init3_failures_retained':True,'max_new_episodes':16,'controller_changed':False,'candidate_changed':False,'not_unseen_test':True},indent=2))""")
s=s.replace('reserved physical selection; frozen automatic candidate; not final test','feasibility replacement development pilot; frozen candidate; exposed histories; not test')
s=s.replace("phase='reserved physical selection'", "phase='feasibility replacement development pilot'")
s=s.replace("'contract-physical-selection-v1'", "'contract-feasible-pilot-v1'")
s=s.replace('Complete all 16 episodes; require joint checkpoints and full-episode completions no worse than parent, plus training gate; report all six comparisons and extra-call control without claiming superiority from two conditions','Complete all 16; expansion trigger is verified joint full-episode successes strictly greater than every other arm; no early stopping or repeated same-config sampling; report all results')
s=s.replace('New instruction permutations for this registered study, not a claim that LIBERO scenes or init indices are globally unseen','Exposed development histories, init2 chosen solely from physical feasibility evidence; not held-out validation or final test')
s=s.replace("m['all_histories']=list(m['all_histories'])+fresh", "m['all_histories']=list(dict.fromkeys(list(m['all_histories'])+fresh))")
s=s.replace("names+=['orders.json'", "names+=['previous-study-results.json','physical-qualification.json','orders.json'")
Path('work/heartbeat-1107/stage.py').write_text(s)
compile(s,'stage.py','exec')
assert "'init':2" in s and "get('completed')==8" in s
print('stage syntax and fixed configuration checks passed')
