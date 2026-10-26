import pathlib,json,os,sys,subprocess,time,hashlib
B=pathlib.Path('/data/songziying/paos-libero-20261023');R=B/'study-rsi-joint-v1';O=R/'learning';OLD=B/'study-rsi-v4-learning-compact/learning'
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
state=read(B/'active-learning.json');assert state['root']==str(R)
assert not pathlib.Path('/proc/'+str(state['pid'])).exists()
assert not (R/'reserved-check-registration.json').exists(),'Already registered; inspect instead of duplicate launch'
assert read(O/'report.json')['status']=='training_complete_pending_independent_selection'
audit=read(OLD/'source-audit.json');used={x['source_id'] for x in read(OLD/'validation/manifest.json')['schedule']}
used|={x['source_id'] for x in read(O/'training/manifest.json')['schedule']}
sources=[x for x in audit['validation']['eligible'] if x['id'] not in used]
assert len(sources)==1 and sources[0]['id']=='hDABCE-v1-i1'
for k in ['training','validation']:
 assert sources[0]['id'] not in {x['id'] for x in audit[k]['selected']}
registration={'time':time.time(),'stage':'unused_reserved_condition_check','sources':sources,
'previous_validation_source_ids':sorted(used),'candidate_hashes':read(O/'candidate-hashes.json'),
'primary':'joint','repetitions':2,'arms':['parent','g_only_edit','u_only_edit','joint'],'maximum_replays':8,
'gate':'Existing score_pair validation non-regression and cost gate plus joint training gate; no candidate selection by best score',
'limitation':'Unused condition shares history with prior validation; not new history generalization',
'proposal_calls':0,'rule_changes':False,'no_automatic_resampling':True,'final_test_accessed':False,
'check_script_sha256':sha(R/'code/check_reserved.py'),'learner_sha256':sha(R/'code/learn.py')}
(R/'reserved-check-registration.json').write_text(json.dumps(registration,indent=2))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(R/'source');env['PAOS_CORE_ROOT']=str(R/'paos-core');env['PYTHONPATH']=':'.join([str(R/'code'),str(R/'code/runtime'),str(R/'code/protocol'),str(R/'source'),str(R/'paos-core'),env.get('PYTHONPATH','')])
with (R/'reserved-check.log').open('x') as f:
 p=subprocess.Popen([sys.executable,str(R/'code/check_reserved.py')],stdin=subprocess.DEVNULL,stdout=f,stderr=f,env=env,start_new_session=True)
state={'root':str(R),'pid':p.pid,'phase':'frozen_joint_unused_condition_check','node':'107','time':time.time()}
(R/'reserved-check-launch.json').write_text(json.dumps(state));(B/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
