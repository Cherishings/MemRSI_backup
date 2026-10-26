import pathlib,json,shutil,hashlib,os,sys,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023')
old=b/'study-rsi-joint-feedback-review-v2';training_root=b/'study-rsi-joint-v1';r=b/'study-rsi-contract-v1';incoming=b/'rsi-contract-v1-incoming'
assert not r.exists(),'Do not duplicate registered version'
state=json.loads((b/'active-learning.json').read_text());assert state['root']==str(old)
assert not pathlib.Path('/proc/'+str(state['pid'])).exists(),'Old learner must have exited'
report=json.loads((old/'learning/report.json').read_text());assert report['status']=='fixed_proposal_review_rejected'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
r.mkdir()
for name in ['code','source']:shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to((old/'paos-core').resolve(),target_is_directory=True)
for name in ['parent-policy.json','budget.json','training-sources.json']:shutil.copy2(old/name,r/name)
# Required CLI identity placeholder only: this controller never inspects validation sources.
(r/'validation-sources.json').write_text('[]\n')
shutil.copy2(incoming/'learn.py',r/'code/learn.py')
shutil.copy2(incoming/'feedback.py',r/'code/feedback.py')
shutil.copy2(incoming/'governance.py',r/'code/governance.py')
shutil.copy2(old/'frozen-proposal.json',r/'previous-rejected-proposal.json')
f=r/'feedback-input/learning';f.mkdir(parents=True)
(f/'training').symlink_to(training_root/'learning/training',target_is_directory=True)
(f/'policies').mkdir();shutil.copy2(training_root/'learning/policies/joint.json',f/'policies/joint.json')
sys.path.insert(0,str(r/'code'))
from feedback import build
feedback=build(r/'feedback-input')
assert len(feedback['summaries'])==32 and len(feedback['joint_contexts'])==8
(r/'feedback-input/registration.json').write_text(json.dumps({'original_training_rows_sha256':sha(training_root/'learning/training/rows.json'),'original_training_manifest_sha256':sha(training_root/'learning/training/manifest.json'),'training_only':True,'previous_joint_sha256':sha(f/'policies/joint.json')}))
ledger=json.loads((old/'learning/learning-call-ledger.json').read_text());assert ledger['limit']==24000
reg={'registered_at':time.time(),'version':'joint-explicit-contract-training-v1','node':'107','previous_root':str(old),
'previous_report_sha256':sha(old/'learning/report.json'),'primary_method':'joint',
'changes':['One joint revision proposal receives all previous training outcomes and joint terminal contexts; original parent evidence remains','Explicit allowed procedural-edit scope; forbidden task answers/runtime changes require exact candidate quote; all pass needed','Single-edit arms remove exactly one component of joint proposal','Training only; previously exposed validation not read'],
'causal_claim':'Previous critic rejected generic procedure changes under an unstated rule-preservation requirement; explicit contract removes that ambiguity, not a guarantee of candidate validity',
'authorization':'User explicitly authorized autonomous code improvements and reruns, hourly review',
'proposal_limit':1,'critic_limit':1,'training_replays_max':32,'repetitions':2,'source_limit':4,
'current_call_limit':24000,'carried_calls':ledger['calls'],'no_automatic_same_configuration_retry':True,
'validation_feedback_in_optimizer':False,'validation_sources_accessed':False,'test_accessed':False,
'final_six_arm_comparison':'Pending frozen candidate and independent evaluation registration; this stage is not that comparison',
'failure_costs_preserved':True,'loader_repair_inherited_from':str(b/'study-rsi-v4-learning-compact/loader-repair-20261024/repair.json'),
'offline_tests_passed':27,'parent_sha256':sha(r/'parent-policy.json'),'budget_sha256':sha(r/'budget.json'),
'files':{str(p.relative_to(r)):sha(p) for folder in ['code','source'] for p in (r/folder).rglob('*.py')}}
(r/'controller-registration.json').write_text(json.dumps(reg,indent=2)+'\n')
(r/'learning').mkdir();(r/'learning/learning-call-ledger.json').write_text(json.dumps(ledger))
(r/'learning/carried-costs.json').write_text(json.dumps({'from':str(old),'previous_calls':ledger['calls'],'raw_cost_logs_retained_at':str(old/'learning'),'include_transitive_carried_costs':True}))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
args=[sys.executable,str(r/'code/learn.py'),'--root',str(r),'--source',str(r/'source'),'--core',str(r/'paos-core'),'--train-manifest',str(r/'training-sources.json'),'--validation-manifest',str(r/'validation-sources.json'),'--parent-policy',str(r/'parent-policy.json'),'--budget',str(r/'budget.json')]
with (r/'controller.log').open('x') as log:
 p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
state={'root':str(r),'pid':p.pid,'time':time.time(),'phase':'joint_explicit_contract_training_only','node':'107'}
(r/'controller-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
