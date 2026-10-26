"""One audited native test4217 retry; preserve both arms and resume original study."""
import fcntl,json,os,subprocess,sys,time,hashlib,importlib.util
from pathlib import Path
R=Path('/data/stormlab/xi/robot');C=R/'official-memory-adapter-v6r1-20261021';O=R/'runs/official-memory-adapter-v6r1-20261021';OUT=O/'rmbench';CODE=Path(__file__).resolve().parent;D=R/'runs/paper-completion-20261020/rmb4217-transport-recovery-20261021';PH='8141d8e412607feec08f7a93430869e0cb2ca8dea2604af8f11b5fc645ea9636';OLD=OUT/'trajectories/test'/PH/'4217';NEW=OLD.with_name('4217-attempt02')
def read(p):return json.loads(Path(p).read_text())
def write(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+f'.{os.getpid()}.tmp');t.write_text(json.dumps(d,indent=2));t.replace(p)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(pid):
 try:
  x=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split();return dict(pid=pid,start_ticks=x[19],state=x[0])
 except FileNotFoundError:return None
def alive(i):
 a=ident(i['pid']);return a and a['start_ticks']==str(i['start_ticks']) and a['state']!='Z'
def spawn(argv,env,label):
 write(D/(label+'-launch-intent.json'),dict(argv=argv,time=time.time()))
 with (D/(label+'.private.log')).open('ab') as f:p=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True,cwd=R)
 write(D/(label+'-child.json'),dict(identity=ident(p.pid),argv=argv,time=time.time()));return p

def main():
 D.mkdir(parents=True,exist_ok=True)
 with (D/'recovery.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if (D/'trial-launch-intent.json').exists():raise RuntimeError('launch_intent_exists_audit_required')
  write(D/'coordinator.json',dict(identity=ident(os.getpid()),gpu=6,time=time.time()))
  try:
   plan=read(O/'launch-plan.json');meta=read(OLD/'started.json');score=read(OLD/'scored-record.json');prior=read(OUT/'coordinator.json')
   assert prior['pid']==885672 and str(prior['start_ticks'])=='366659074' and not alive(prior),'old_coordinator_not_retired'
   assert not alive(meta['identity']) and not any(alive(x['identity']) for x in read(OLD/'child-processes.json')),'prior_children_alive'
   entries=read(meta['attempt_ledger'])['cases'][meta['attempt_key']]
   assert len(entries)==1 and entries[0]['status']=='technical_failure' and entries[0]['output']==str(OLD),'attempt_ledger_changed'
   assert meta['attempt']==1 and score['status']=='technical_failure' and score['method']=='native' and score['seed']==4217 and score['policy_sha256']==PH,'prior_identity_mismatch'
   assert not NEW.exists(),'retry_output_exists'
   sys.path[:0]=[str(C),str(C/'common')];spec=importlib.util.spec_from_file_location('frozen_trial',C/'run_trial.py');rt=importlib.util.module_from_spec(spec);spec.loader.exec_module(rt)
   assert rt.source_hashes()==plan['source_hashes']==meta['source_hashes'],'frozen_source_changed'
   ev=read(CODE/'gateway-evidence.json');errors=[json.loads(x) for x in (OLD/'actor/model-errors.jsonl').read_text().splitlines()];err=errors[-1];detail=err.get('error',err)
   # Evidence layout is independently checked before launch; bind immutable files.
   assert ev['request_sha256'] in (OLD/'actor/model-errors.jsonl').read_text(),'exact_request_not_found'
   audit=dict(approved=True,reason='Audited terminal provider stream ended without response.completed; source-branch reproduction excludes output-limit event. Retry only affected native test4217 once under existing technical max3 authorization.',prior_output=str(OLD),prior_result_sha256=sha(OLD/'result.json'),prior_score_sha256=sha(OLD/'scored-record.json'),public_errors_sha256=sha(OLD/'actor/model-errors.jsonl'),gateway_evidence=ev,requested_attempt=2,max_attempts=3,automatic_third_attempt=False,source_unchanged=True,all_prior_calls_retained=True,formal_feedback_not_used_for_learning=True,time=time.time())
   write(D/'audit.json',audit)
   for f in ['coordinator.json','paused.json','adaptation-state.json','progress.json','study-launched.json']:
    if (OUT/f).exists():write(D/('prior-'+f),read(OUT/f))
   env=dict(plan['environment'],CUDA_VISIBLE_DEVICES='6',MEMRSI_OFFLINE_WAIT='1',MEMRSI_PARALLEL_BUDGET='1')
   argv=[plan['python'],str(C/'run_trial.py'),'--benchmark','rmbench','--phase','test','--method','native','--seed','4217','--gpu','6','--policy',str(C/'policies/initial.json'),'--ledger',plan['ledger'],'--retry-audit',str(D/'audit.json'),'--output',str(NEW)]
   write(D/'progress.json',dict(phase='audited_attempt2',output=str(NEW),time=time.time()));p=spawn(argv,env,'trial');p.wait()
   assert (NEW/'scored-record.json').exists(),'retry_incomplete'
   score=read(NEW/'scored-record.json');assert score['status'] in {'success','task_failure','protocol_failure','capacity_failure','budget_failure','decision_failure','physical_failure'},'retry_technical_requires_new_audit'
   assert not any(alive(x['identity']) for x in read(NEW/'child-processes.json')),'retry_children_alive'
   assert rt.source_hashes()==plan['source_hashes'],'source_changed_after_retry'
   argv=[plan['python'],str(CODE/'study-map.py'),str(C)]+prior['argv'][3:]
   p=spawn(argv,env,'study');record=dict(**ident(p.pid),gpu=6,version='adapter-v6r1-audited4217-cache',time=time.time(),argv=argv)
   write(OUT/'coordinator.json',record);write(OUT/'study-launched.json',record);write(D/'study-launched.json',record);write(D/'progress.json',dict(phase='original_full_study_resumed',retry_status=score['status'],coordinator=record,time=time.time()))
  except Exception as e:
   write(D/'paused.json',dict(reason=str(e) if isinstance(e,AssertionError) else 'inspect_structured_artifacts',error_type=type(e).__name__,automatic_retry=False,time=time.time()));raise
if __name__=='__main__':main()
