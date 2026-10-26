"""Audited technical replay recovery; frozen methods/selection unchanged."""
import argparse,asyncio,fcntl,hashlib,json,os,sys,time
from pathlib import Path

def read(p):return json.loads(Path(p).read_text())
def file_sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def transport_evidence(attempt,result):
    if result.get('error_code')!='native_session_archival_failed':return None
    audits=sorted(Path(attempt).glob('rollover-*/audit.json'),key=lambda p:int(p.parent.name.split('-')[-1]))
    if not audits:return None
    a=read(audits[-1])
    if a.get('success') is not False:return None
    ep=Path(attempt)/'model-errors.jsonl'
    if not ep.exists():return None
    matches=[json.loads(x) for x in ep.read_text().splitlines() if json.loads(x).get('call')==a.get('model_calls')]
    if not matches:return None
    e=matches[-1]
    if e.get('http_status') not in (429,502,503,504):return None
    return {k:e.get(k) for k in ['http_status','code','stage','output_started','retryable','call']}

def next_attempt(old_count,dest):
    if old_count>=3:raise RuntimeError('technical_attempts_exhausted')
    n=old_count+1
    if (Path(dest)/f'attempt-{n:02d}').exists():raise RuntimeError('existing_recovery_attempt_requires_audit')
    return n

async def repair(args):
    code=Path(args.code);sys.path.insert(0,str(code));sys.path.insert(0,str(code/'frozen_runtime'))
    from protocol import verify_runtime,sha
    from budget_account import BudgetAccount,atomic_json
    from trajectory_replay import evaluate,fixture
    from run_learning import Control
    import model_provider
    import transport_wait_override
    transport_wait_override.install(model_provider)
    root=Path(args.root);old=root/'studies'/args.run_id;out=Path(args.audit).parent/'recovery'/args.run_id
    out.mkdir(parents=True,exist_ok=True)
    with (out/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verify_runtime(code)
        manifest=read(old/'manifest.json');auth=read(root/'authorization.json');plan=read(root/'plan-authorized-resume-20261020.json')
        approved=auth['runs'][args.run_id]
        if approved['max_new_calls']!=3000 or auth['required_global_limit']!=15000:raise RuntimeError('authorization_changed')
        account=BudgetAccount(root/'learning-ledger.json',args.run_id,3000,sha(manifest));account.register()
        model_provider.reserve_learning_call=account.reserve
        model_provider.LEARNING_LEDGER.set(root/'learning-ledger.json')
        atomic_json(out/'coordinator.json',dict(pid=os.getpid(),start_ticks=Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')',1)[1].split()[19],run_id=args.run_id,audit_sha256=file_sha(args.audit),scope='cycle-0 confirmed technical recovery only',automatic_cycle1=False))
        control=Control(out)
        rows=[x for x in read(args.audit)['confirmed_transport'] if x['run_id']==args.run_id and x['relative'].startswith('cycle-0/')]
        completed=[]
        try:
            for x in rows:
                src=Path(x['replay']);dest=out/x['relative'];dest.mkdir(parents=True,exist_ok=True)
                if (dest/'result.json').exists():
                    recovered=read(dest/'result.json')
                    if recovered['status'] in ('technical_failure','unclassified_failure','learning_budget_exhausted'):raise RuntimeError('recovery_not_valid')
                    completed.append(str(dest));continue
                if file_sha(src/'result.json')!=x['original_result_sha256']:raise RuntimeError('source_evidence_changed')
                attempts=sorted(src.glob('attempt-*'));last=attempts[-1]
                if len(attempts)!=x['old_attempt_count'] or not transport_evidence(last,read(src/'result.json')):raise RuntimeError('transport_evidence_mismatch')
                policy=read(last/'policy.json')
                if file_sha(last/'policy.json')!=x['policy_sha256']:raise RuntimeError('policy_changed')
                f=fixture(x['source'])
                prior=read(last/'fixture-audit.json')
                if f['sha256']!=prior['sha256']:raise RuntimeError('source_fixture_changed')
                n=next_attempt(len(attempts),dest)
                control.state('technical_replay_recovery',source=x['relative'],attempt=n)
                await asyncio.to_thread(control.wait_gateway)
                atomic_json(dest/'recovery-audit.json',dict(original=x,attempt=n,policy_unchanged=True,source_sha256=f['sha256'],original_attempts_retained=True))
                new=dest/f'attempt-{n:02d}'
                r=await evaluate(f,new,policy,Path(plan['learning_commands'][0]['argv'][plan['learning_commands'][0]['argv'].index('--budget')+1]))
                evidence=transport_evidence(new,r)
                if evidence:r=dict(r,status='technical_failure',original_wrapper_status=r['status'],confirmed_provider_failure=evidence)
                r=dict(r,logical_calls=read(new/'calls.json').get('calls',0) if (new/'calls.json').exists() else 0,attempts=n,original_result=str(src/'result.json'),repair_result=True)
                atomic_json(dest/'result.json',r)
                if r['status'] in ('technical_failure','unclassified_failure','learning_budget_exhausted'):raise RuntimeError('new_technical_failure_requires_audit')
                completed.append(str(dest))
            atomic_json(out/'report.json',dict(status='cycle0_recovered_pending_selection_reconciliation',completed=completed,old_selection_quarantined=True,cycle1_not_started=True,budget=account.register(),note='Reconcile cycle0 with unchanged selector before repairing cycle1 under possibly stale parent policy.'))
            control.state('cycle0_recovered_pending_selection_reconciliation',completed=len(completed))
        except Exception as e:
            safe={'optimizer_call_budget','technical_attempts_exhausted','new_technical_failure_requires_audit','existing_recovery_attempt_requires_audit','source_evidence_changed','transport_evidence_mismatch','policy_changed','source_fixture_changed','recovery_not_valid'}
            atomic_json(out/'paused.json',dict(status='paused',code=str(e) if str(e) in safe else 'inspect_structured_artifacts',error_type=type(e).__name__,completed=completed,no_automatic_retry=True))
            raise SystemExit(2)

def main():
    p=argparse.ArgumentParser();p.add_argument('--code',required=True);p.add_argument('--root',required=True);p.add_argument('--audit',required=True);p.add_argument('--run-id',required=True);a=p.parse_args()
    import setproctitle;setproctitle.setproctitle('robot')
    asyncio.run(repair(a))
if __name__=='__main__':main()
