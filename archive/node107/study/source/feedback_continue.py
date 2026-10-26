"""Resume only unstarted trials after a confirmed transport recovery.

Keep all prior terminal rows, including infrastructure failures and cancellations.
Never regenerate the accepted policy, reset a case or modify an earlier result.
"""
import argparse,concurrent.futures,fcntl,json,os,signal,subprocess,threading,time
from pathlib import Path
from run_queue import ROOT,BASE,env,identity
from replay import dump
from feedback_protocol import schedule,plan,histories
from feedback_queue import summarize,paired,TECH
from physical_runner import PhysicalRunner,PORTS,AGENT_PYTHON,same_process
from memory_policy import BASE as BASE_POLICY,digest,load
from resume_support import UNCHANGED_RUNTIME,read,sha
from feedback_learning import improves

TERMINAL={'success','decision_failure','execution_failure','infrastructure_failure','protocol_failure','budget_failure','guidance_failure','cancelled'}

def pending_rows(rows,planned):
    index={x['trial_id']:x for x in planned};seen=set()
    for row in rows:
        tid=row['trial_id']
        if tid in seen or tid not in index or row['status'] not in TERMINAL:raise ValueError('invalid_parent_rows')
        if any(row.get(k)!=v for k,v in index[tid].items()):raise ValueError('changed_trial_design')
        seen.add(tid)
    return [r for r in planned if r['trial_id'] not in seen]

def inspect(parent,probe):
    parent=Path(parent);progress=read(parent/'progress.json');launch=read(parent.parent/'launch.json')
    if progress.get('active') or progress['status']!='technical_hold':raise ValueError('parent_not_held')
    identities=[read(parent/'coordinator.json'),read(parent/'learning-process.json')]
    identities.extend(read(p) for p in (parent/'gpu-workers').glob('policy-*.identity.json'))
    rows=read(parent/'rows.json');identities.extend(r['worker'] for r in rows)
    if any(same_process(r) for r in identities):raise ValueError('parent_process_alive')
    manifest=read(parent/'manifest.json')
    if manifest['schedule']!=schedule() or manifest['protocols']!=json.loads(json.dumps({h:plan(h) for h in sorted(histories())})):
        raise ValueError('changed_protocol')
    oldroot=Path(launch['code'])
    if any((ROOT/n).read_bytes()!=(oldroot/n).read_bytes() for n in UNCHANGED_RUNTIME):raise ValueError('runtime_changed')
    core=read(ROOT/'pristine-core-manifest.json')
    if core['mismatches'] or any(sha(ROOT/n)!=v for n,v in core['core_sha256'].items()):raise ValueError('core_changed')
    report=read(parent/'learning/report.json');frozen=read(parent/'policy-freeze.json');policy=load(parent/'policies/evolved.json')
    if report['status']!='accepted' or report['promotions']!=1:raise ValueError('learning_not_accepted')
    if digest(policy)!=report['policy_sha256'] or frozen['evolved']!=digest(policy) or frozen['base']!=digest(BASE_POLICY):raise ValueError('policy_mismatch')
    if sha(parent/'learning/report.json')!=frozen['learning_report_sha256']:raise ValueError('learning_report_changed')
    accepted=[x for x in report['attempts'] if x['decision']=='accepted']
    if len(accepted)!=1 or digest(accepted[0]['candidate'])!=digest(policy):raise ValueError('accepted_candidate_mismatch')
    if not improves(report['baseline_development'],accepted[0]['development']) or not improves(accepted[0]['validation_parent'],accepted[0]['validation_candidate']):raise ValueError('acceptance_not_reproduced')
    if load(parent/'policies/fixed.json')!=BASE_POLICY:raise ValueError('fixed_policy_changed')
    probe=Path(probe);check=read(probe)
    if check['status']!='passed' or check['model']!='gpt-5.6-luna' or len(check['checks'])!=2 or not all(x['valid'] for x in check['checks']):raise ValueError('probe_failed')
    if time.time()-probe.stat().st_mtime>1800:raise ValueError('probe_stale')
    pending=pending_rows(rows,schedule())
    return rows,pending,policy,{'parent':str(parent),'parent_rows_sha256':sha(parent/'rows.json'),
        'learning_report_sha256':sha(parent/'learning/report.json'),'policy_sha256':digest(policy),
        'probe_path':str(probe),'probe_sha256':sha(probe),'retained_terminal_rows':len(rows),'pending':len(pending),
        'unchanged_runtime_files':list(UNCHANGED_RUNTIME),'unchanged_core_files':len(core['core_sha256']),
        'episode_retries':0,'old_failure_and_cancelled_attempts_retained':True}

def main(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False);stop=threading.Event();mutex=threading.RLock();active={};rows=[];planned=schedule();reason={};status='failed'
    gpu_dir=out/'gpu-workers';gpu_dir.mkdir();runner=PhysicalRunner(gpu_dir,stop,gpus=(0,1,6,7))
    def state(status='running',**extra):
        with mutex:dump(out/'progress.json',dict(status=status,planned=len(planned),terminal=len(rows),active=dict(active),updated_unix=time.time(),**extra))
    def halt(*_):reason['stop']='user_cancelled';stop.set()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,halt)
    dump(out/'coordinator.json',identity(os.getpid()))
    try:
        rows,pending,policy,audit=inspect(a.parent,a.probe);parent=Path(a.parent)
        dump(out/'resume-provenance.json',audit);dump(out/'rows.json',rows);dump(out/'summary.json',summarize(rows,planned));dump(out/'paired.json',paired(rows))
        for name in ('selected-orders.json','budget.json','policy-freeze.json'):(out/name).write_bytes((parent/name).read_bytes())
        dump(out/'policies/fixed.json',BASE_POLICY);dump(out/'policies/evolved.json',policy)
        # Read-only references for the status viewer. No new learning process.
        (out/'learning').symlink_to(parent/'learning',target_is_directory=True)
        dump(out/'learning-process.json',read(parent/'learning-process.json'))
        files={p.name:sha(p) for p in ROOT.glob('*.py')}
        dump(out/'manifest.json',dict(read(parent/'manifest.json'),version='memrsi-transport-resume-v1.2',resumed_from=str(parent),
            source_sha256=files,transport_probe=audit,learning_rerun=False,retained_terminal_rows=len(rows),new_trials=len(pending),trial_retries=0))
        runner.acquire(state)
        def lane(gpu):
            bad=0
            for row in (r for r in pending if r['gpu']==gpu):
                if stop.is_set():return
                if any(sha(ROOT/n)!=h for n,h in files.items()):raise RuntimeError('source_changed')
                dest=out/'evaluation'/row['trial_id'];dest.parent.mkdir(parents=True,exist_ok=True)
                cmd=[AGENT_PYTHON,str(ROOT/'feedback_workflow.py'),'--output',str(dest),'--orders',str(out/'selected-orders.json'),
                     '--budget',str(out/'budget.json'),'--port',str(PORTS[gpu]),'--init',str(row['init']),'--variant','0','--history',row['history'],
                     '--arm','native' if row['arm']=='native' else 'memrsi']
                if row['arm']!='native':cmd+=['--memory-policy',str(out/'policies'/f"{row['arm']}.json")]
                with dest.with_suffix('.log').open('xb') as log:
                    child=subprocess.Popen(cmd,cwd=ROOT,env=env(gpu),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
                ident=runner.track(child,'worker')
                with mutex:active[str(gpu)]=dict(row,output=str(dest),worker=ident);state()
                started=time.monotonic();error=None
                try:
                    while child.poll() is None:
                        if stop.wait(2):error='cancelled';break
                        if time.monotonic()-started>10800:error='worker_timeout';break
                    if error:runner.stop_owned(child)
                    result=read(dest/'result.json') if (dest/'result.json').exists() else {'status':'infrastructure_failure','error_code':'worker_exit'}
                    if error:result.update(status='cancelled' if error=='cancelled' else 'infrastructure_failure',error_code=error)
                    result.update(row,output=str(dest),worker=ident)
                finally:
                    if child.poll() is None:runner.stop_owned(child)
                    runner.release_process(child)
                with mutex:
                    rows.append(result);active.pop(str(gpu),None);dump(out/'rows.json',rows);dump(out/'summary.json',summarize(rows,planned));dump(out/'paired.json',paired(rows));state()
                bad=bad+1 if result['status'] in TECH else 0
                if bad>=2:reason['stop']='technical_hold';stop.set();return
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            futures=[pool.submit(lane,gpu) for gpu in (0,1,6,7)]
            for future in concurrent.futures.as_completed(futures):
                try:future.result()
                except Exception:stop.set();raise
        status='completed' if len(rows)==len(planned) else reason.get('stop','incomplete')
    except Exception as exc:
        dump(out/'queue-failure.json',{'type':type(exc).__name__,'code':str(exc) if str(exc).replace('_','').isalnum() else 'inspect_structured_outputs'})
    finally:
        runner.close();dump(out/'report.json',{'status':status,'terminal':len(rows),'planned':len(planned),'summary':summarize(rows,planned),
          'pending':[r['trial_id'] for r in planned if r['trial_id'] not in {x['trial_id'] for x in rows}]});state(status)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('output','parent','probe'):p.add_argument('--'+name,required=True)
    main(p.parse_args())
