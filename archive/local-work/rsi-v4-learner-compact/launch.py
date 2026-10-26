import pathlib,json,shutil,hashlib,os,sys,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study-rsi-v4-learning';r=b/'study-rsi-v4-learning-compact'
assert not r.exists(),'Do not duplicate learner'
report=json.loads((old/'learning/report.json').read_text());assert report['status']=='no_qualified_update' and not report['training'] and not report['validation']
state=json.loads((b/'active-learning.json').read_text());assert state['root']==str(old)
assert not pathlib.Path('/proc/'+str(state['pid'])).exists(),'Previous learner must exit'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
r.mkdir()
for name in ['code','source']:shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to(old/'paos-core',target_is_directory=True)
for name in ['parent-policy.json','budget.json','training-sources.json','validation-sources.json']:shutil.copy2(old/name,r/name)
shutil.copy2(b/'rsi-v4-incoming/learn-compact.py',r/'code/learn.py')
reg={'registered_at':time.time(),'version':'optimizer-representation-v2','single_controller_node':'107','previous_root':str(old),'previous_report_sha256':sha(old/'learning/report.json'),'previous_outcome':'no_qualified_update','previous_costs_retained':True,'changes':['Replace source audit file hash maps with digest references; full originals retained','Represent exact repeated long evidence strings once, with references; retain all selected cases and all semantic evidence before existing budget truncation','Ask for one short local edit with margin below unchanged hard length limits'],'observed_previous_failures':['G output limit 8192','U replacement1329 exceeds1200'],'causal_claim':'Input duplication is an observed inefficiency, not proof of the cause of output failure','proposal_limit_this_version':{'guidance':1,'update':1},'total_proposal_attempts_across_versions_max':4,'automatic_next_version':False,'hard_constraints_changed':False,'same_parent_sources_selection_replays_and_validation_gate':True,'validation_feedback_used_for_revision':False,'test_feedback_used':False,'physical_test_started':False,'offline_tests_passed':18,'parent_sha256':sha(r/'parent-policy.json'),'training_manifest_sha256':sha(r/'training-sources.json'),'validation_manifest_sha256':sha(r/'validation-sources.json'),'files':{str(p.relative_to(r)):sha(p) for folder in ['code','source'] for p in (r/folder).rglob('*.py')}}
(r/'controller-registration.json').write_text(json.dumps(reg,indent=2)+'\n')
(r/'learning').mkdir();ledger=json.loads((old/'learning/learning-call-ledger.json').read_text());assert ledger['limit']==24000 and ledger['calls']==2
(r/'learning/learning-call-ledger.json').write_text(json.dumps(ledger));(r/'learning/carried-costs.json').write_text(json.dumps({'from':str(old),'previous_calls':ledger['calls'],'raw_cost_logs_retained_at':str(old/'learning'),'all_prior_costs_must_be_included':True}))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
args=[sys.executable,str(r/'code/learn.py'),'--root',str(r),'--source',str(r/'source'),'--core',str(r/'paos-core'),'--train-manifest',str(r/'training-sources.json'),'--validation-manifest',str(r/'validation-sources.json'),'--parent-policy',str(r/'parent-policy.json'),'--budget',str(r/'budget.json')]
with (r/'controller.log').open('x') as log:p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
state={'root':str(r),'pid':p.pid,'time':time.time(),'phase':'automatic_learning_compact_v2','node':'107'};(r/'controller-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
