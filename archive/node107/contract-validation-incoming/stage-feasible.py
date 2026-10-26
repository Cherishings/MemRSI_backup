"""New reserved physical comparison; never changes candidate or final-test inputs."""
import json,pathlib,shutil,hashlib,sys,os,time,subprocess,itertools
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study-contract-validation-v1';r=b/'study-contract-feasible-pilot-v1';inc=b/'contract-validation-incoming'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert not r.exists(),'No duplicate selection study'
assert read(b/'active-study.json')['root']==str(old)
q=read(old/'queue-status.json');assert q.get('completed')==8
assert len(list((old/'development').glob('*/*/result.json')))==8
assert not pathlib.Path('/proc/'+str(q['pid'])).exists()
m=read(old/'registration.json');a=read(old/'allocation.json');node=str(a['node']);idx={'107':0,'108':1}[node]
used=set(m['all_histories']);fresh=['ABCDE','ABECD']
condition={'condition_id':f'h{fresh[idx]}-v{idx}-i2','history':fresh[idx],'variant':idx,'init':2}
r.mkdir()
summary=[]
for p in sorted((old/'development').glob('*/*/result.json')):
 d=read(p);summary.append({'arm':p.parent.name,'path':str(p),'sha256':sha(p),'status':d['status'],'classification':('method_archive_protocol_failure' if d.get('error_code')=='native_session_archival_failed' else d['status']),'correct_checkpoints':d.get('correct_checkpoints'),'sessions_completed':d.get('sessions_completed'),'model_cost_complete':d.get('model_cost_complete'),'input_tokens':d.get('model_input_tokens'),'output_tokens':d.get('model_output_tokens')})
(r/'previous-study-results.json').write_text(json.dumps(summary,indent=2))
(r/'physical-qualification.json').write_text(json.dumps({'selection_basis':'executor feasibility only, not method ranking','source_node':107,'source_result':'study-contract-validation-v1/development/hABCDE-v0-i2/think_u/result.json','verified':{'physical_successes':20,'rollovers':19,'checkpoints':7,'finish_correct':True,'bowl_executions':3,'bowl_policy_calls_each':22},'replacement':'same task, init2 for all arms on both distinct histories','old_init3_failures_retained':True,'max_new_episodes':16,'controller_changed':False,'candidate_changed':False,'not_unseen_test':True},indent=2))
for name in ['code','source']:shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to((old/'paos-core').resolve(),target_is_directory=True)
for name in ['orders.json','budget.json','parent-policy.json','env.sh']:shutil.copy2(old/name,r/name)
for p in list((r/'code').rglob('*.py'))+list((r/'source').glob('*.py'))+[r/'env.sh']:
 p.write_text(p.read_text().replace(str(old),str(r)))
# Inherit already tested loader compatibility; do not alter policy or simulation.
for name in ['memory_policy.py','memory_design.py']:shutil.copy2(inc/name,r/'source'/name)
shutil.copy2(inc/'learned-policy.json',r/'learned-policy.json')
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
import method
parent=read(r/'parent-policy.json');learned=read(r/'learned-policy.json');assert parent!=learned
arms=['native','g_only','u_only','gu_parent','gu_learned','rsi_g_only','rsi_u_only','think_u']
policies={arm:method.policy_for(parent,parent if arm in ['g_only','u_only'] else learned,arm) for arm in arms}
assert policies['g_only']['guidance']==parent['guidance'] and policies['u_only']['update']==parent['update']
assert policies['gu_learned']==learned
assert policies['rsi_g_only']['update']==parent['update'] and policies['rsi_u_only']['guidance']==parent['guidance']
(r/'policies').mkdir()
for arm,p in policies.items():(r/'policies'/f'{arm}.json').write_text(json.dumps(p,indent=2))
p=r/'code/case_v2.py';s=p.read_text().replace("assert j['arm'] in ('native','g_only','u_only','gu_parent','think_u')", "assert j['arm'] in ('native','g_only','u_only','gu_parent','gu_learned','rsi_g_only','rsi_u_only','think_u')")
s=s.replace("parent=json.loads((r/'parent-policy.json').read_text());policy=method.policy_for(parent,parent,j['arm'])", "policy=json.loads((r/'policies'/f\"{j['arm']}.json\").read_text())")
s=s.replace('development only; manually improved parent, not RSI result','feasibility replacement development pilot; frozen candidate; exposed histories; not test')
p.write_text(s)
order=arms[idx:]+arms[:idx];schedule=[dict(condition,arm=arm,output=str(r/'development'/condition['condition_id']/arm)) for arm in order]
(r/'development-schedule.json').write_text(json.dumps(schedule,indent=2));a.update(phase='feasibility replacement development pilot',allowed_condition_ids=[condition['condition_id']],final_test_allowed=False)
(r/'allocation.json').write_text(json.dumps(a,indent=2))
for name in ['jobs','logs']:(r/name).mkdir()
reg={'version':'contract-feasible-pilot-v1','registered_at':time.time(),'node':node,'all_reserved_histories':fresh,
'prior_registered_histories':sorted(used),'condition':condition,'arms':arms,'primary':'gu_learned',
'candidate_sha256':method.digest(learned),'parent_sha256':method.digest(parent),'per_node_jobs':8,'total_jobs':16,
'method_changes':False,'budget_changes':False,'selection_rule':'Complete all 16; expansion trigger is verified joint full-episode successes strictly greater than every other arm; no early stopping or repeated same-config sampling; report all results',
'failure_policy':'No method retries; infrastructure failure pauses queue; preserve all attempts and costs',
'optimizer_may_read_results':False,'final_test_started':False,'physical_exposure_caveat':'Exposed development histories, init2 chosen solely from physical feasibility evidence; not held-out validation or final test',
'policy_file_hashes':{arm:sha(r/'policies'/f'{arm}.json') for arm in arms}}
(r/'selection-registration.json').write_text(json.dumps(reg,indent=2))
m['all_histories']=list(dict.fromkeys(list(m['all_histories'])+fresh));m['administrative_amendments'].append(reg)
# Freeze every deployed Python file and every input used by this queue.
names=[str(p.relative_to(r)) for folder in ['code','source'] for p in (r/folder).rglob('*.py')]
names+=['previous-study-results.json','physical-qualification.json','orders.json','budget.json','parent-policy.json','learned-policy.json','allocation.json','development-schedule.json','selection-registration.json','env.sh']+[f'policies/{arm}.json' for arm in arms]
m['frozen_files']={n:sha(r/n) for n in names}
(r/'registration.json').write_text(json.dumps(m,indent=2));(r/'registration.sha256').write_text(sha(r/'registration.json'))
from run_case import verify
verify(r)
from planning import bind_registered_plan
# Import and validate the plan binding without any model or simulator execution.
import twenty_protocol
bound=bind_registered_plan(twenty_protocol.plan,m['all_histories'])
assert callable(bound)
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
os.environ['PYTHONPATH']=os.environ.get('PYTHONPATH','').replace(str(old),str(r))
with (r/'queue.log').open('x') as f:p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True,env=os.environ.copy())
(r/'queue-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}));(b/'active-study.json').write_text(json.dumps({'root':str(r),'time':time.time()}))
print(json.dumps({'node':node,'root':str(r),'pid':p.pid,'condition':condition,'jobs':8}))
