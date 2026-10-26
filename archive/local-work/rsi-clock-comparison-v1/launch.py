import pathlib,json,shutil,hashlib,os,sys,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study-rsi-transition-v1';r=b/'study-rsi-clock-comparison-v1';incoming=b/'rsi-clock-comparison-v1-incoming'
assert not r.exists(),'No repeated registered comparison'
state=json.loads((b/'active-learning.json').read_text());assert state['root']==str(old);assert not pathlib.Path('/proc/'+str(state['pid'])).exists()
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert len(read(old/'learning/training/rows.json'))==32
r.mkdir()
for name in ['code','source']:shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to((old/'paos-core').resolve(),target_is_directory=True)
for name in ['budget.json','training-sources.json','parent-policy.json']:shutil.copy2(old/name,r/name)
for name in ['check.py','replay_clock.py']:shutil.copy2(incoming/name,r/'code'/name)
shutil.copy2(incoming/'trajectory_replay.py',r/'source/trajectory_replay.py')
s=r/'code/learn.py';text=s.read_text();assert text.count('"maximum_parallel_replays": 2')==1
text=text.replace('"maximum_parallel_replays": 2','"maximum_parallel_replays": 4').replace('tasks = [asyncio.create_task(worker()), asyncio.create_task(worker())]','tasks = [asyncio.create_task(worker()) for _ in range(4)]');s.write_text(text)
sys.path[:0]=[str(r/'code'),str(r/'source'),str(r/'paos-core')]
import learn
out=r/'learning';(out/'policies').mkdir(parents=True)
locations={'parent':old/'parent-policy.json','old_joint':b/'study-rsi-joint-v1/learning/policies/joint.json','latest_joint':old/'learning/policies/joint.json'}
for arm,path in locations.items():shutil.copy2(path,out/'policies'/(arm+'.json'))
sources=read(old/'learning/source-audit.json')['training']['selected'];assert len(sources)==4
ledger=read(old/'learning/learning-call-ledger.json');assert ledger=={'calls':4565,'limit':24000}
reg={'registered_at':time.time(),'purpose':'Fixed-policy training development comparison after observed wall-clock input mismatch; not independent validation or final test','arms':list(locations),'policy_hashes':{n:learn.digest(read(p)) for n,p in locations.items()},'policy_origin':{n:str(p) for n,p in locations.items()},'sources':sources,'max_replays':24,'repetitions':2,'parallel_replays':4,'node':'107','proposal_calls':0,'critic_calls':0,'same_config_retries':0,'carried_calls':4565,'call_limit':24000,'selection':'Original score_pair gate; among passing joint policies rank completed descending, correct descending, logical_calls ascending, stable arm name; no single-edit substitution. Candidate selected only for separately registered eight-arm physical pilot; no efficacy claim.','clock':'Replay-visible time=2026-10-23T00:00 plus event id minutes. Native session add_message, actor save_turn and prompt Current Time use this shared semantic clock. Real transport/cost/timeout clocks unchanged.','limits':['Prior old_joint validation failure remains; this is exposed training development','Clock repair removes confirmed input variation, not proof it caused score regression','Nominal model version unchanged; upstream hidden routing cannot be established from existing logs'],'tests':'4 unit and 4 real component checks, zero model calls. Initial real check found local datetime import in _save_turn; wrapper preserves native saving and changes only newly saved timestamps; retested.','files':{str(p.relative_to(r)):sha(p) for folder in ['code','source'] for p in (r/folder).rglob('*.py')},'budget_sha256':sha(r/'budget.json'),'runtime_core':str((r/'paos-core').resolve())}
(r/'comparison-registration.json').write_text(json.dumps(reg,indent=2));(out/'learning-call-ledger.json').write_text(json.dumps(ledger));(out/'carried-costs.json').write_text(json.dumps({'from':str(old),'raw_costs_retained':True,'include_transitive_carried_costs':True,'physical_costs_separate':True}))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
with (r/'controller.log').open('x') as log:p=subprocess.Popen([sys.executable,str(r/'code/check.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
state={'root':str(r),'pid':p.pid,'time':time.time(),'phase':'fixed_three_policy_clock_comparison','node':'107'};(r/'controller-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
