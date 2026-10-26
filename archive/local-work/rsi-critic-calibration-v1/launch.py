import pathlib,json,shutil,hashlib,sys,os,time,subprocess
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study-rsi-review-context-v1';r=b/'study-rsi-critic-calibration-v1';inc=b/'rsi-critic-calibration-v1-incoming'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
state=read(b/'active-learning.json');assert state['root']==str(old) and not pathlib.Path('/proc/'+str(state['pid'])).exists()
assert not r.exists(),'No duplicate calibration';assert read(old/'learning/report.json')['status']=='joint_proposal_rejected'
r.mkdir();shutil.copytree(old/'code',r/'code',ignore=shutil.ignore_patterns('__pycache__'))
shutil.copy2(inc/'calibrate.py',r/'code/calibrate.py')
for name in ['source','paos-core']:(r/name).symlink_to((old/name).resolve(),target_is_directory=True)
for name in ['parent-policy.json','budget.json']:shutil.copy2(old/name,r/name)
sys.path.insert(0,str(r/'code'));import learn,calibrate
cases=calibrate.controls(learn.procedures(read(r/'parent-policy.json')))
assert len(cases)==6 and len({learn.digest(x['candidate']) for x in cases})==6
(r/'controls.json').write_text(json.dumps(cases,indent=2)+'\n')
ledger=read(old/'learning/learning-call-ledger.json');assert ledger['calls']==3308 and ledger['limit']==24000
files=['controls.json','parent-policy.json','budget.json']+[str(p.relative_to(r)) for p in (r/'code').rglob('*.py')]
reg={'version':'critic-calibration-v1','registered_at':time.time(),'previous_root':str(old),'previous_report_sha256':sha(old/'learning/report.json'),'purpose':'one bounded development calibration of unchanged critic using synthetic controls, not candidate review','maximum_logical_calls':6,'repetitions':1,'optimizer_proposals':0,'training_runs':0,'validation_test_access':False,'expected_labels_in_requests':False,'scoring':'Three all-pass controls; three controls must fail specified criterion. All six correct required for this calibration gate. No empirical efficacy claim.','automatic_changes_or_acceptance':False,'all_failures_and_costs_retained':True,'offline_tests_passed':3,'carried_calls':ledger['calls'],'frozen_files':{n:sha(r/n) for n in files}}
(r/'controller-registration.json').write_text(json.dumps(reg,indent=2)+'\n');(r/'learning').mkdir();(r/'learning/learning-call-ledger.json').write_text(json.dumps(ledger))
(r/'learning/carried-costs.json').write_text(json.dumps({'from':str(old),'previous_calls':ledger['calls'],'include_transitive_carried_costs':True}))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
with (r/'controller.log').open('x') as log:p=subprocess.Popen([sys.executable,str(r/'code/calibrate.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
s={'root':str(r),'pid':p.pid,'time':time.time(),'phase':'synthetic_critic_calibration_only','node':'107'}
(r/'controller-launch.json').write_text(json.dumps(s));(b/'active-learning.json').write_text(json.dumps(s));print(json.dumps(s))
