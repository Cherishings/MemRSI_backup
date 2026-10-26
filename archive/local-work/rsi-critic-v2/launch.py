import pathlib,json,hashlib,shutil,os,sys,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study-rsi-joint-feedback-v1';r=b/'study-rsi-joint-feedback-review-v2';inc=b/'critic-v2-incoming'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert not r.exists(),'No repeated review'
state=read(b/'active-learning.json');assert state['root']==str(old)
assert not (pathlib.Path('/proc')/str(state['pid'])).exists()
report=read(old/'learning/report.json');assert report['status']=='joint_proposal_rejected'
assert report['proposal_decisions']['joint']['rejection']['code']=='critic_rejected'
r.mkdir()
for f in ['code','source']:shutil.copytree(old/f,r/f,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to((old/'paos-core').resolve(),target_is_directory=True)
for f in ['parent-policy.json','budget.json','training-sources.json']:shutil.copy2(old/f,r/f)
shutil.copy2(inc/'review.py',r/'code/review.py')
shutil.copy2(old/'learning/proposals/joint/value.json',r/'frozen-proposal.json')
sys.path.insert(0,str(r/'code'));import learn
proposal=read(r/'frozen-proposal.json');combos=learn.joint_combinations(read(r/'parent-policy.json'),proposal)
reg={'version':'critic-explicit-verdict-v2','time':time.time(),'previous_root':str(old),
'previous_rejection_sha256':sha(old/'learning/proposal-decisions.json'),'proposal_file_sha256':sha(r/'frozen-proposal.json'),
'proposal_canonical_sha256':learn.digest(proposal),'candidate_hashes':{k:learn.digest(v) for k,v in combos.items()},
'change':'Replace underspecified Boolean criteria with explicit pass/fail enum plus reason per criterion; program derives acceptance',
'rereview_limit':1,'proposal_generation_calls':0,'max_training_replays':32,'old_rejection_retained':True,
'old_critic_not_sent_to_new_critic':True,'failure_behavior':'Stop on fail, malformed output or unavailable result; no same-review retry',
'validation_read':False,'test_read':False,'tests_passed':3,'review_sha256':sha(r/'code/review.py')}
(r/'controller-registration.json').write_text(json.dumps(reg,indent=2))
(r/'learning').mkdir();ledger=read(old/'learning/learning-call-ledger.json');assert ledger['calls']==1979
(r/'learning/learning-call-ledger.json').write_text(json.dumps(ledger));(r/'learning/carried-costs.json').write_text(json.dumps({'from':str(old),'calls':ledger['calls'],'include_all_transitive_costs':True}))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
with (r/'controller.log').open('x') as f:p=subprocess.Popen([sys.executable,str(r/'code/review.py'),str(r)],stdin=subprocess.DEVNULL,stdout=f,stderr=f,env=env,start_new_session=True)
state={'root':str(r),'pid':p.pid,'phase':'fixed_proposal_explicit_critic_once','node':'107','time':time.time()}
(r/'controller-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
