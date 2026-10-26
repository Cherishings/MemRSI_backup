"""Register and launch a bounded five-arm manual-parent development comparison."""
import json,pathlib,shutil,hashlib,sys,os,time,subprocess
b=pathlib.Path('/data/songziying/paos-libero-20261023')
old=b/'study-scope-v3-technical1';baseline=b/'study-scope-v3';r=b/'study-scope-v4'
assert not r.exists(), 'Do not duplicate registered run'
assert json.loads((b/'active-study.json').read_text())['root']==str(old)
q=json.loads((old/'queue-status.json').read_text())
assert q['phase']=='development_complete'
assert not pathlib.Path('/proc/'+str(q['pid'])).exists(), 'Prior dispatcher must exit'
node=str(json.loads((old/'allocation.json').read_text())['node'])
condition={'107':'hEDABC-v1-i0','108':'hEADCB-v1-i1'}[node]
arms=['native','g_only','u_only','gu_parent','think_u']
baseline_rows=[]
for arm in arms:
 p=baseline/'development'/condition/arm/'result.json'
 d=json.loads(p.read_text())
 if d['status']=='infrastructure_failure':
  p=old/'development'/condition/arm/'result.json';d=json.loads(p.read_text())
 assert d['status'] not in ('infrastructure_failure','technical_failure','execution_failure','unclassified_failure')
 baseline_rows.append({'arm':arm,'result':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                       'status':d['status'],'sessions_completed':d['sessions_completed'],
                       'correct_checkpoints':d['correct_checkpoints']})
candidate=b/'v4-incoming/candidate-parent.json'
assert hashlib.sha256(candidate.read_bytes()).hexdigest()=='85b302d366686e8cd02611e704bac7c744c99d4ae1f75695afcf97fcbcb5803a'
r.mkdir()
for name in ('code','source','policies'):
 shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to(old/'paos-core',target_is_directory=True)
for name in ('orders.json','budget.json','allocation.json','env.sh'):
 shutil.copy2(old/name,r/name)
for p in list((r/'code').rglob('*.py'))+list((r/'source').glob('*.py'))+[r/'env.sh']:
 p.write_text(p.read_text().replace(str(old),str(r)))
shutil.copy2(candidate,r/'parent-policy.json')
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
import method
parent=json.loads(candidate.read_text());method.validate_policy(parent);method.guidance_procedure(parent)
for arm in arms:
 (r/'policies'/f'{arm}.json').write_text(json.dumps(method.policy_for(parent,None,arm),indent=2)+'\n')
schedule=[dict(j,output=str(r/'development'/condition/j['arm'])) for j in json.loads((baseline/'development-schedule.json').read_text()) if j['condition_id']==condition]
assert len(schedule)==5 and set(j['arm'] for j in schedule)==set(arms)
(r/'development-schedule.json').write_text(json.dumps(schedule,indent=2)+'\n')
for name in ('jobs','logs'):(r/name).mkdir()
(r/'baseline-paired-results.json').write_text(json.dumps(baseline_rows,indent=2)+'\n')
registration={'kind':'manual_parent_revision_development','not_RSI':True,
 'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
 'changes':['G target/authority/catalog precondition checks','U authorization and continuation obligation retention'],
 'development_conditions':[condition],'arms':arms,'planned_jobs':5,
 'all_five_arms_run_regardless_of_intermediate_scores':True,
 'infrastructure_failure_stops_dispatch':True,'no_method_changes_mid_comparison':True,
 'hardware_and_budgets_unchanged':True,'previous_failures_and_costs_preserved':True,
 'next_gate':'Complete both node five-arm development blocks before assessing candidate; no final-test feedback or automatic RSI claim',
 'registered_at':time.time()}
(r/'manual-revision.json').write_text(json.dumps(registration,indent=2)+'\n')
m=json.loads((old/'registration.json').read_text());m['registered_at']=time.time()
m['administrative_amendments'].append(registration)
# Technical replacement record belongs to the prior root, not this new method.
m['frozen_files'].pop('technical-replacement.json',None)
for name in m['frozen_files']:m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
for name in ['manual-revision.json','baseline-paired-results.json','parent-policy.json']:
 m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n')
(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
from run_case import verify
verify(r)
assert (r/'budget.json').read_bytes()==(old/'budget.json').read_bytes()
assert 'infrastructure_failure' in (r/'code/queue_v2.py').read_text()
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
os.environ['PYTHONPATH']=os.environ.get('PYTHONPATH','').replace(str(old),str(r))
import runtime_adapter
runtime_adapter.configure(7,20517,str(r/'paos-core'))
import model_provider
assert model_provider.OUTPUT_CAP==8192
with (r/'queue.log').open('x') as log:
 p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=os.environ.copy())
(r/'queue-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}))
tmp=b/'active-study.tmp';tmp.write_text(json.dumps({'root':str(r),'time':time.time()}));tmp.replace(b/'active-study.json')
print(json.dumps({'node':node,'root':str(r),'queue_pid':p.pid,'jobs':len(schedule),'first':schedule[0]}))
