"""One audited U-only candidate technical attempt2; never an automatic third."""
import argparse,asyncio,fcntl,hashlib,json,os,subprocess,sys,time
from pathlib import Path
R=Path('/data/stormlab/xi/robot');CODE=R/'paper-evolution-20261018r1';REPAIR=R/'runs/paper-completion-20261020/archive-transport-repair';RUN='update_only-order100';OUT=REPAIR/'corrected-cycle1'/RUN;CASE=OUT/'cycle-1/candidate-replays/dev-11-r1-candidate';AUDIT=OUT/'technical-dev11-r1-20261020'
def read(p):return json.loads(Path(p).read_text())
def sha_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(pid=None):
 pid=pid or os.getpid();s=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split();return dict(pid=pid,start_ticks=s[19])
def check():
 sys.path[:0]=[str(CODE),str(CODE/'frozen_runtime'),str(R/'paper-completion-20261020/archive-transport-repair')]
 from protocol import verify_runtime,sha
 from trajectory_replay import fixture
 from repair_archives import transport_evidence
 old=R/'runs/paper-evolution-20261018/studies'/RUN;manifest=read(old/'manifest.json')
 if verify_runtime(CODE)!=manifest['runtime_sha256']:raise RuntimeError('frozen_runtime_changed')
 result=read(CASE/'result.json');attempt=CASE/'attempt-01';e=transport_evidence(attempt,result)
 if result['status']!='technical_failure' or result['attempts']!=1 or e.get('http_status')!=502 or e.get('call')!=4:raise RuntimeError('audited_failure_changed')
 if sorted(p.name for p in CASE.glob('attempt-*'))!=['attempt-01']:raise RuntimeError('attempt_identity_changed')
 if read(OUT/'paused.json')['code']!='unresolved_parent_technical':raise RuntimeError('pause_changed')
 previous=read(OUT/'coordinator.json');proc=Path(f'/proc/{previous["pid"]}/stat')
 if proc.exists() and ident(previous['pid'])['start_ticks']==str(previous['start_ticks']):raise RuntimeError('coordinator_still_live')
 prior=read(attempt/'fixture-audit.json');f=fixture(prior['source']);f['id']='dev-11'
 if f['sha256']!=prior['sha256']:raise RuntimeError('fixture_changed')
 policy=read(attempt/'policy.json')
 if policy!=read(OUT/'cycle-1/candidate-policy.json'):raise RuntimeError('candidate_changed')
 for p in (old/'cycle-1/candidate-replays/dev-11-r1-candidate').glob('attempt-*/policy.json'):
  if read(p)==policy:raise RuntimeError('old_candidate_attempt_collision')
 ledger=R/'runs/paper-evolution-20261018/learning-ledger.json';budget=read(ledger)
 if budget['authorized_limit']!=15000 or budget['paper_evolution_runs'][RUN]['limit']!=3000:raise RuntimeError('budget_changed')
 record=dict(case=str(CASE),source_sha256=f['sha256'],policy_sha256=sha_file(attempt/'policy.json'),original_result_sha256=sha_file(CASE/'result.json'),provider_evidence=e,old_attempt=1,next_attempt=2,max_attempt=3,no_automatic_third=True,original_account=RUN,account_manifest_sha256=sha(manifest),original_calls=read(attempt/'calls.json')['calls'],previous_coordinator=previous)
 return record,f,policy,manifest,ledger
async def main(validate):
 from contextlib import nullcontext
 AUDIT.mkdir(exist_ok=True)
 with (OUT/'coordinator.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  record,f,policy,manifest,ledger=check()
  from budget_account import BudgetAccount,atomic_json
  from protocol import sha,immutable_write
  immutable_write(AUDIT/'audit.json',record,atomic_json)
  if validate:
   print(json.dumps(dict(passed=True,new_model_calls=0,**record)));return
  from trajectory_replay import evaluate
  from run_learning import Control
  from repair_archives import transport_evidence
  import model_provider,transport_wait_override
  transport_wait_override.install(model_provider)
  account=BudgetAccount(ledger,RUN,3000,sha(manifest));account.register();model_provider.reserve_learning_call=account.reserve;model_provider.LEARNING_LEDGER.set(ledger)
  atomic_json(AUDIT/'coordinator.json',dict(**ident(),time=time.time(),attempt=2))
  for name in ['paused.json','coordinator.json']:
   immutable_write(AUDIT/('original-'+name),read(OUT/name),atomic_json)
  immutable_write(AUDIT/'original-result.json',read(CASE/'result.json'),atomic_json)
  try:
   control=Control(AUDIT);control.state('audited_technical_attempt2',case='dev-11-r1-candidate')
   await asyncio.to_thread(control.wait_gateway)
   plan=read(R/'runs/paper-evolution-20261018/plan-authorized-resume-20261020.json');argv=next(x['argv'] for x in plan['learning_commands'] if RUN in x['argv']);budget=Path(argv[argv.index('--budget')+1])
   dest=CASE/'attempt-02';result=await evaluate(f,dest,policy,budget);e=transport_evidence(dest,result)
   if e and e.get('code')!='generation_output_limit':result=dict(result,status='technical_failure',original_wrapper_status=result['status'],confirmed_provider_failure=e)
   calls=read(dest/'calls.json')['calls'] if (dest/'calls.json').exists() else 0
   result=dict(result,attempts=2,logical_calls=calls,all_attempt_calls=record['original_calls']+calls,tokens=result.get('model_input_tokens',0)+result.get('model_output_tokens',0),cost_complete=result.get('model_cost_complete',False))
   atomic_json(CASE/'result.json',result)
   if result['status'] in ('technical_failure','unclassified_failure','learning_budget_exhausted'):raise RuntimeError('new_technical_failure_requires_audit')
   atomic_json(AUDIT/'report.json',dict(status='valid_attempt2_resume_original_study',result_status=result['status'],all_attempt_calls=result['all_attempt_calls'],no_automatic_third=True))
   (OUT/'paused.json').rename(AUDIT/'cleared-paused.json')
  except Exception as e:
   atomic_json(AUDIT/'paused.json',dict(code=str(e) if str(e) in ['new_technical_failure_requires_audit','optimizer_call_budget'] else 'inspect_structured_artifacts',error_type=type(e).__name__,automatic_retry=False));return
 # Original frozen study reuses all valid cases and the audited attempt2 result.
 script=R/'paper-completion-20261020/archive-transport-repair/resume_corrected_cycle1_r2.py'
 with (OUT/'worker-after-dev11.private.log').open('ab') as log:
  p=subprocess.Popen([sys.executable,str(script),'--run-id',RUN],cwd=R,env=os.environ.copy(),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 atomic_json(AUDIT/'study-launched.json',dict(**ident(p.pid),time=time.time(),same_output=True,attempts_preserved=True))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--validate',action='store_true');a=ap.parse_args();asyncio.run(main(a.validate))
