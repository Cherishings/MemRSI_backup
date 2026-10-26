"""Continue corrected cycle1 under the original account and frozen learning algorithm.
No stale candidate/diagnosis reuse; new output is evidence-only, not a new budget.
"""
import argparse,asyncio,copy,fcntl,hashlib,json,os,sys,time,types
from pathlib import Path
R=Path('/data/stormlab/xi/robot');CODE=R/'paper-evolution-20261018r1';ROOT=R/'runs/paper-evolution-20261018';REPAIR=R/'runs/paper-completion-20261020/archive-transport-repair'
def read(p):return json.loads(Path(p).read_text())
def file_sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident():
 a=Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')',1)[1].split();return dict(pid=os.getpid(),start_ticks=a[19])
def manifest_matches(new,old):
 a=copy.deepcopy(new);a['study_output']=old['study_output']
 if a!=old:raise RuntimeError('registered_protocol_changed')
def valid_result(r):
 if r['status'] in ('technical_failure','unclassified_failure','learning_budget_exhausted'):raise RuntimeError('unresolved_parent_technical')
 return r
async def drain_gather(*tasks,**kwargs):
 vals=await asyncio.gather(*tasks,return_exceptions=True)
 for v in vals:
  if isinstance(v,BaseException):raise v
 return vals

def prepare(run):
 sys.path[:0]=[str(CODE),str(CODE/'frozen_runtime'),str(R/'paper-completion-20261020/archive-transport-repair')]
 import run_learning as learning
 from protocol import sha,verify_runtime,immutable_write
 from budget_account import atomic_json,BudgetAccount
 from diagnosed_learning import source_sets
 from stream_design import compile_procedures
 from repair_archives import transport_evidence
 import model_provider,transport_wait_override
 transport_wait_override.install(model_provider)
 old=ROOT/'studies'/run;out=REPAIR/'corrected-cycle1'/run;out.mkdir(parents=True,exist_ok=True)
 rec=REPAIR/'reconciliation'/run;recovery=REPAIR/'cycle1-parent-recovery'/run
 report=read(rec/'report.json');completed=read(recovery/'report.json');manifest=read(old/'manifest.json')
 if report['status']!='reconciled' or report['unresolved'] or report['effect']['accepted']:raise RuntimeError('cycle0_not_complete_rejected')
 if completed['status']!='cycle1_parent_recovered_pending_fresh_diagnosis' or len(completed['completed'])!=8:raise RuntimeError('parent_recovery_not_complete')
 if (recovery/'paused.json').exists():raise RuntimeError('parent_recovery_paused')
 runtime=verify_runtime(CODE)
 if runtime!=manifest['runtime_sha256']:raise RuntimeError('runtime_changed')
 if file_sha(old/'cycle-0/parent-policy.json')!=report['parent_policy_file_sha256']:raise RuntimeError('cycle0_parent_changed')
 parent=read(old/'cycle-1/parent-policy.json')
 if parent!=read(old/'cycle-0/parent-policy.json') or parent!=compile_procedures(manifest['initial_procedures']):raise RuntimeError('parent_policy_changed')
 command=next(x['argv'] for x in read(ROOT/'plan-authorized-resume-20261020.json')['learning_commands'] if run in x['argv'])
 params={command[i][2:].replace('-','_'):command[i+1] for i in range(len(command)-1) if command[i].startswith('--')}
 for k in ['order_seed','max_new_calls']:params[k]=int(params[k])
 args=types.SimpleNamespace(**params);args.output=str(out)
 auth=learning.authorize(args)
 if args.max_new_calls!=3000:raise RuntimeError('budget_limit_changed')
 account=BudgetAccount(args.global_ledger,run,3000,sha(manifest));account.register()
 training,_=source_sets(args.source_prior)
 from protocol import ordered_sources
 fs=ordered_sources(training,args.order_seed)[1];expected={f'{f["id"]}-r{n}-parent':f for f in fs for n in range(2)}
 rows=[];provenance=[]
 for name,f in expected.items():
  src=old/'cycle-1/parent-replays'/name;fixed=recovery/'cycle-1/parent-replays'/name;dest=out/'cycle-1/parent-replays'/name
  a=read(fixed/'recovery-audit.json');original=a['original'];result=valid_result(read(fixed/'result.json'));n=result['attempts'];last=fixed/f'attempt-{n:02d}'
  if original['run_id']!=run or original['relative']!=f'cycle-1/parent-replays/{name}':raise RuntimeError('parent_identity_changed')
  if file_sha(src/'result.json')!=original['original_result_sha256'] or file_sha(last/'policy.json')!=original['policy_sha256']:raise RuntimeError('parent_evidence_changed')
  if read(last/'policy.json')!=parent or read(last/'fixture-audit.json')['sha256']!=f['sha256']:raise RuntimeError('parent_fixture_changed')
  if transport_evidence(last,result):raise RuntimeError('parent_transport_unresolved')
  attempts=sorted(src.glob('attempt-*'))+sorted(fixed.glob('attempt-*'))
  if len(attempts)>3 or len(attempts)!=n:raise RuntimeError('parent_attempt_identity')
  total=sum(read(p/'calls.json')['calls'] for p in attempts)
  if total<read(src/'result.json').get('all_attempt_calls',0):raise RuntimeError('cost_reset')
  value=dict(result,all_attempt_calls=total)
  dest.mkdir(parents=True,exist_ok=True)
  for p in attempts:
   link=dest/p.name
   if link.exists():
    if link.resolve()!=p.resolve():raise RuntimeError('attempt_link_changed')
   else:link.symlink_to(p.resolve(),target_is_directory=True)
  immutable_write(dest/'result.json',value,atomic_json)
  rows.append(value);provenance.append(dict(case=name,original=str(src),recovery=str(fixed),source_hash=file_sha(fixed/'result.json'),all_attempt_calls=total))
 selection=dict(parent_sha256=sha(parent),selected=manifest['initial_procedures'],effect=report['effect'])
 immutable_write(out/'cycle-0/parent-policy.json',parent,atomic_json);immutable_write(out/'cycle-0/selection.json',selection,atomic_json)
 lineage=dict(original_manifest_sha256=sha(manifest),original_study=str(old),corrected_cycle0_report_sha256=file_sha(rec/'report.json'),completed_parent_report_sha256=file_sha(recovery/'report.json'),parent_provenance=provenance,original_account=run,per_run_limit=3000,global_limit=15000,stale_diagnosis_proposal_candidate_not_copied=True,frozen_algorithm_source_sha256=file_sha(CODE/'run_learning.py'))
 immutable_write(out/'recovery-lineage.json',lineage,atomic_json)
 original_immutable=learning.immutable_write;original_account=learning.BudgetAccount
 def write_manifest(path,value,writer):
  if Path(path)==out/'manifest.json':manifest_matches(value,manifest)
  return original_immutable(path,value,writer)
 def same_account(path,run_id,limit,protocol_hash):
  new=read(out/'manifest.json');manifest_matches(new,manifest)
  if run_id!=run or limit!=3000 or protocol_hash!=sha(new):raise RuntimeError('account_binding_changed')
  return original_account(path,run_id,limit,sha(manifest))
 learning.immutable_write=write_manifest;learning.BudgetAccount=same_account
 # Preserve complete sibling results if one concurrent replay fails technically.
 proxy=types.SimpleNamespace(gather=drain_gather,to_thread=asyncio.to_thread)
 learning.asyncio=proxy
 import trajectory_evolution as te,diagnosed_learning as dl
 from trajectory_replay import evaluate
 te.asyncio=proxy
 async def guarded_replay(f,path,policy,budget,wait_gateway):
  path=Path(path);path.mkdir(parents=True,exist_ok=True)
  if (path/'result.json').exists():return valid_result(read(path/'result.json'))
  if list(path.glob('attempt-*')):raise RuntimeError('partial_replay_requires_audit')
  # A regenerated proposal that duplicates an old candidate needs an identity audit,
  # never a silent fourth attempt or repeated valid capability result.
  rel=path.relative_to(out);prior=old/rel
  for a in prior.glob('attempt-*'):
   if (a/'policy.json').exists() and read(a/'policy.json')==policy:raise RuntimeError('old_candidate_identity_requires_audit')
  await asyncio.to_thread(wait_gateway)
  dest=path/'attempt-01';r=await evaluate(f,dest,policy,budget);e=transport_evidence(dest,r)
  if e and e.get('code')!='generation_output_limit':r=dict(r,status='technical_failure',original_wrapper_status=r['status'],confirmed_provider_failure=e)
  calls=read(dest/'calls.json').get('calls',0) if (dest/'calls.json').exists() else 0
  r=dict(r,attempts=1,logical_calls=calls,all_attempt_calls=calls,tokens=r.get('model_input_tokens',0)+r.get('model_output_tokens',0),cost_complete=r.get('model_cost_complete',False))
  atomic_json(path/'result.json',r);return valid_result(r)
 te.replay_case=guarded_replay
 old_requests={read(p)['sha256'] for p in old.glob('cycle-1/**/request-identity.json')}
 original_structured=dl.safe_structured
 async def new_structured(path,system,data,schema,wait_gateway):
  signature=hashlib.sha256(json.dumps([system,data,schema],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  if signature in old_requests:raise RuntimeError('old_optimizer_request_requires_audit')
  return await original_structured(path,system,data,schema,wait_gateway)
 dl.safe_structured=new_structured
 return learning,args,dict(runtime_sha256=runtime),out,lineage

def main():
 import setproctitle;setproctitle.setproctitle('robot')
 ap=argparse.ArgumentParser();ap.add_argument('--run-id',required=True);ap.add_argument('--prepare-only',action='store_true');ap.add_argument('--validate-entry',action='store_true');a=ap.parse_args()
 out=REPAIR/'corrected-cycle1'/a.run_id;out.mkdir(parents=True,exist_ok=True)
 with (out/'coordinator.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  from contextlib import suppress
  try:
   learning,args,identity,out,lineage=prepare(a.run_id)
   from budget_account import atomic_json
   if a.prepare_only:print(json.dumps(dict(run=a.run_id,parents=len(lineage['parent_provenance']),model_calls=0,prepared=True)));return
   if a.validate_entry:
    import transition_diagnosis as td
    class EntryVerified(Exception):pass
    async def stop_before_model(*v,**kw):
     if len(v[2])!=8:raise RuntimeError('missing_corrected_parent_rows')
     raise EntryVerified()
    td.diagnosed_packet=stop_before_model
    before=read(ROOT/'learning-ledger.json')['paper_evolution_runs'][a.run_id]['calls']
    try:asyncio.run(learning.learn(args,learning.Control(out),identity))
    except EntryVerified:pass
    else:raise RuntimeError('diagnosis_boundary_not_reached')
    after=read(ROOT/'learning-ledger.json')['paper_evolution_runs'][a.run_id]['calls']
    if before!=after:raise RuntimeError('validation_charged_calls')
    atomic_json(out/'zero-call-entry-validation.json',dict(passed=True,parents=8,before=before,after=after,original_account_unchanged=True))
    print(json.dumps(dict(run=a.run_id,entry_validated=True,model_calls=0)));return
   if (out/'report.json').exists():raise RuntimeError('existing_report_requires_audit')
   if (out/'paused.json').exists():raise RuntimeError('existing_pause_requires_audit')
   atomic_json(out/'coordinator.json',dict(**ident(),run_id=a.run_id,time=time.time(),original_account_preserved=True))
   control=learning.Control(out);asyncio.run(learning.learn(args,control,identity))
  except Exception as e:
   from budget_account import atomic_json
   safe={'old_optimizer_request_requires_audit','old_candidate_identity_requires_audit','partial_replay_requires_audit','unresolved_parent_technical','optimizer_call_budget','optimizer_technical_attempts_exhausted'}
   atomic_json(out/'paused.json',dict(code=str(e) if str(e) in safe else 'inspect_structured_artifacts',error_type=type(e).__name__,automatic_retry=False,time=time.time()))
   raise SystemExit(2)
if __name__=='__main__':main()
