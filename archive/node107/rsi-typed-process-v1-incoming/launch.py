import pathlib,json,shutil,hashlib,os,sys,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023')
old=b/'study-rsi-process-edit-v1';template=b/'study-rsi-review-context-v1';training_root=b/'study-rsi-training-feedback-v2';r=b/'study-rsi-typed-process-v1';incoming=b/'rsi-typed-process-v1-incoming'
assert not r.exists(),'Do not duplicate registered version'
state=json.loads((b/'active-learning.json').read_text());assert state['root']==str(old)
assert not pathlib.Path('/proc/'+str(state['pid'])).exists(),'Old learner must have exited'
report=json.loads((old/'learning/report.json').read_text());assert report['status']=='joint_proposal_rejected'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
r.mkdir()
shutil.copy2(old/'process-scope-audit.json',r/'process-scope-evidence.json')
for name in ['code','source']:shutil.copytree(template/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to((template/'paos-core').resolve(),target_is_directory=True)
for name in ['parent-policy.json','budget.json','training-sources.json']:shutil.copy2(template/name,r/name)
# Required CLI identity placeholder only: this controller never inspects validation sources.
(r/'validation-sources.json').write_text('[]\n')
shutil.copy2(incoming/'learn.py',r/'code/learn.py')
shutil.copy2(incoming/'anchor_catalog.py',r/'code/anchor_catalog.py')
shutil.copy2(incoming/'runtime_contract.py',r/'code/runtime_contract.py')
shutil.copy2(template/'learning/proposals/joint/value.json',r/'previous-review-rejected-proposal.json')
shutil.copy2(b/'study-rsi-anchor-catalog-v1/learning/proposals/joint/value.json',r/'previous-review-rejected-proposal-anchor.json')
shutil.copy2(incoming/'process_compiler.py',r/'code/process_compiler.py')
shutil.copy2(old/'learning/proposals/joint/value.json',r/'previous-review-rejected-proposal-process.json')
shutil.copy2(incoming/'feedback.py',r/'code/feedback.py')
shutil.copy2(incoming/'citation_contract.py',r/'code/citation_contract.py')
shutil.copy2(incoming/'governance.py',r/'code/governance.py')
shutil.copy2(training_root/'learning/proposals/joint/value.json',r/'previous-rejected-proposal.json')
f=r/'feedback-input/learning';f.mkdir(parents=True)
(f/'training').symlink_to(training_root/'learning/training',target_is_directory=True)
(f/'policies').mkdir();shutil.copy2(training_root/'learning/policies/joint.json',f/'policies/joint.json')
sys.path.insert(0,str(r/'code'))
from feedback import build
feedback=build(r/'feedback-input')
assert len(feedback['summaries'])==32 and len(feedback['joint_contexts'])==8
(r/'feedback-input/registration.json').write_text(json.dumps({'original_training_rows_sha256':sha(training_root/'learning/training/rows.json'),'original_training_manifest_sha256':sha(training_root/'learning/training/manifest.json'),'training_only':True,'previous_joint_sha256':sha(f/'policies/joint.json')}))
ledger=json.loads((old/'learning/learning-call-ledger.json').read_text());assert ledger['limit']==24000
reg={'registered_at':time.time(),'version':'joint-typed-process-selection-v1','node':'107','previous_root':str(old),
'process_scope_evidence_sha256':sha(r/'process-scope-evidence.json'),'previous_report_sha256':sha(old/'learning/report.json'),'primary_method':'joint',
'changes':['Select one G and one U operation jointly from a frozen human-authored two-by-two catalog','Reject free text, extra keys and unknown operations; compile selected operations into local append patches','Critic SYSTEM/SCHEMA/verdict, runtime validator, budget, parent and training evidence unchanged','Single joint selection, not enumeration of all four candidates; exact component ablations'],
'causal_claim':'Prior lexical scope checks allowed natural-language protocol restatements. A finite compiler bounds emitted text structurally, but restricts learning to human-authored operation selection and does not prove improved decisions or critic reliability.',
'method_limitation':'Human-authored finite search space; not autonomous rule-text invention',
'authorization':'User explicitly authorized autonomous code improvements and reruns, hourly review',
'proposal_limit':1,'critic_limit':1,'training_replays_max':32,'repetitions':2,'source_limit':4,
'current_call_limit':24000,'carried_calls':ledger['calls'],'no_automatic_same_configuration_retry':True,
'validation_feedback_in_optimizer':False,'validation_sources_accessed':False,'test_accessed':False,
'final_six_arm_comparison':'Pending frozen candidate and independent evaluation registration; this stage is not that comparison',
'failure_costs_preserved':True,'loader_repair_inherited_from':str(b/'study-rsi-v4-learning-compact/loader-repair-20261024/repair.json'),
'offline_tests_passed':48,'offline_test_note':'48 tests passed before launch; initial real-parent comparison exposed space/newline mismatch, corrected compiler to existing patcher newline and added integration regression. No model calls during correction.','parent_sha256':sha(r/'parent-policy.json'),'budget_sha256':sha(r/'budget.json'),
'files':{str(p.relative_to(r)):sha(p) for folder in ['code','source'] for p in (r/folder).rglob('*.py')}}
(r/'controller-registration.json').write_text(json.dumps(reg,indent=2)+'\n')
(r/'learning').mkdir();(r/'learning/learning-call-ledger.json').write_text(json.dumps(ledger))
(r/'learning/carried-costs.json').write_text(json.dumps({'from':str(old),'previous_calls':ledger['calls'],'raw_cost_logs_retained_at':str(old/'learning'),'include_transitive_carried_costs':True,'additional_physical_cost_roots':[str(b/'study-contract-validation-v1'),str(b/'study-contract-feasible-pilot-v1'),str(b/'study-feedback-v2-physical-pilot')],'physical_costs_separate_from_learner_ledger':True}))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
args=[sys.executable,str(r/'code/learn.py'),'--root',str(r),'--source',str(r/'source'),'--core',str(r/'paos-core'),'--train-manifest',str(r/'training-sources.json'),'--validation-manifest',str(r/'validation-sources.json'),'--parent-policy',str(r/'parent-policy.json'),'--budget',str(r/'budget.json')]
with (r/'controller.log').open('x') as log:
 p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
state={'root':str(r),'pid':p.pid,'time':time.time(),'phase':'joint_typed_operation_selection_training_only','node':'107'}
(r/'controller-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
