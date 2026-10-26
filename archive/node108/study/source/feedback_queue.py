"""Four-GPU sealed 120-trial comparison; never relabel unchanged rules as evolved."""
import argparse,concurrent.futures,json,os,signal,subprocess,threading,time
from pathlib import Path
from run_queue import ROOT,BASE,env,identity,stop_group
from replay import dump
from physical_runner import PhysicalRunner,PORTS,AGENT_PYTHON
from memory_policy import BASE as BASE_POLICY,digest,load
from twenty_queue import qualification,sha,PHYSICAL_FILES
from feedback_protocol import schedule,plan
from resume_support import inspect_parent
TECH={'infrastructure_failure','protocol_failure','budget_failure','guidance_failure'}

def summarize(rows,planned):
    out={}
    for arm in ('native','fixed','evolved'):
        rs=[r for r in rows if r['arm']==arm];counts={}
        for r in rs:counts[r['status']]=counts.get(r['status'],0)+1
        reached=sum(r.get('reached_checkpoints',0) for r in rs);correct=sum(r.get('correct_checkpoints',0) for r in rs);answered=sum(r.get('answered_checkpoints',0) for r in rs)
        out[arm]={'planned_trials':sum(x['arm']==arm for x in planned),'terminal_trials':len(rs),'status_counts':counts,
            'planned_checkpoints_terminal':7*len(rs),'reached':reached,'answered':answered,'correct':correct,
            'coverage_terminal':reached/(7*len(rs)) if rs else None,'accuracy_given_answer':correct/answered if answered else None}
    return out

def paired(rows):
    groups={}
    for r in rows:groups.setdefault((r['condition'],r['repeat']),{})[r['arm']]=r
    return [{'condition':k[0],'repeat':k[1],'arms':{a:{'status':r['status'],'correct':r.get('correct_checkpoints',0),'reached':r.get('reached_checkpoints',0)} for a,r in v.items()},
        'complete_triplet':set(v)=={'native','fixed','evolved'}} for k,v in groups.items()]

def main(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False);stop=threading.Event();mutex=threading.RLock();active={};rows=[];planrows=schedule();reason={};learning=None
    gpu_dir=out/'gpu-workers';gpu_dir.mkdir();runner=PhysicalRunner(gpu_dir,stop,gpus=(0,1,6,7))
    def state(status='running',**extra):
        with mutex:dump(out/'progress.json',{'status':status,'planned':len(planrows),'terminal':len(rows),'active':dict(active),'updated_unix':time.time(),**extra})
    def halt(*_):reason['stop']='user_cancelled';stop.set()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,halt)
    status='failed';dump(out/'coordinator.json',identity(os.getpid()))
    try:
        qualification(a.qualification,a.reverse)
        if a.resume:
            rows,provenance=inspect_parent(a.resume)
            dump(out/'resume-provenance.json',provenance)
            dump(out/'rows.json',rows);dump(out/'summary.json',summarize(rows,planrows));dump(out/'paired.json',paired(rows))
        (out/'selected-orders.json').write_bytes(Path(a.orders).read_bytes());dump(out/'budget.json',json.loads((ROOT/'configs/selected-budget.json').read_text()))
        dump(out/'policies/fixed.json',BASE_POLICY)
        files={p.name:sha(p) for p in ROOT.glob('*.py')}
        dump(out/'manifest.json',{'version':'memrsi-real-feedback-v1.1','resumed_from':a.resume,'reused_terminal_trials':len(rows),'gpus':[0,1,6,7],'schedule':planrows,
            'planned_trials':120,'unique_conditions':20,'repeats':2,'arms':['native','fixed','evolved'],
            'sessions':20,'switches':19,'partial_tables':5,'checkpoints':7,'budget':json.loads((out/'budget.json').read_text()),
            'physical_source_sha256':{n:sha(ROOT/n) for n in PHYSICAL_FILES},'source_sha256':files,
            'protocols':{h:plan(h) for h in sorted({r['history'] for r in planrows})},
            'test_split':'new priority sequences not exposed to optimizer; known task families and physical initial states, not globally unseen objects/environments',
            'source_evidence':'old v3 outcomes explicitly reclassified development/validation; never counted as new heldout successes',
            'baseline':'unchanged PAOS core/session/archive prompt; shared action/capacity adapters',
            'memory_changes':'only evolved guidance/update procedure strings; fixed uses original BASE strings',
            'physical_skills_unchanged':True,'no_expected_answer_to_actor':True,'no_finish_veto':True,
            'capacity_revision':'same 1024 hard limit; neutral compression target 70%, feedback measured size and retry target60%; two attempts, atomic rollback',
            'trial_retries':0,'episode_timeout_seconds':a.episode_timeout,'per_trial_model_calls':480,
            'learning_max_proposals':2,'pilot_trials':4,'evolved_gate':'changed hash plus positive paired dev and independent validation; unchanged/no-benefit policy is never run as evolved',
            'request_admission':'existing shared serialized luna lock; four robot workers, not four simultaneous model calls',
            'scope':'real simulated gripper; one serial robot per episode, externally routed preserved scenes',
            'statistics':'paired by condition and repetition; repetitions are not additional task diversity',
            'stop_rule':'stop expansion on any pilot technical failure; during main run hold after two consecutive technical failures in a lane, preserve all outcomes'})
        def guard():
            if any(sha(ROOT/n)!=h for n,h in files.items()):raise RuntimeError('source_changed')
        with (out/'learning.log').open('xb') as log:
            learning_cmd=[AGENT_PYTHON,str(ROOT/'feedback_learning.py'),'--output',str(out/'learning')]
            if a.resume:learning_cmd+=['--resume-learning',str(Path(a.resume)/'learning')]
            learning=subprocess.Popen(learning_cmd,cwd=ROOT,env=env(0),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
        dump(out/'learning-process.json',identity(learning.pid))
        if not a.resume:runner.acquire(state)
        def lane(gpu,selected,policies):
            bad=0
            for row in selected:
                if stop.is_set():return
                guard();dest=out/'evaluation'/row['trial_id'];dest.parent.mkdir(parents=True,exist_ok=True)
                cmd=[AGENT_PYTHON,str(ROOT/'feedback_workflow.py'),'--output',str(dest),'--orders',str(out/'selected-orders.json'),
                    '--budget',str(out/'budget.json'),'--port',str(PORTS[gpu]),'--init',str(row['init']),'--variant','0','--history',row['history'],
                    '--arm','native' if row['arm']=='native' else 'memrsi']
                if row['arm']!='native':cmd+=['--memory-policy',str(policies[row['arm']])]
                with dest.with_suffix('.log').open('xb') as log:
                    child=subprocess.Popen(cmd,cwd=ROOT,env=env(gpu),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
                ident=runner.track(child,'worker')
                with mutex:active[str(gpu)]=dict(row,output=str(dest),worker=ident);state()
                start=time.monotonic();error=None
                try:
                    while child.poll() is None:
                        if stop.wait(2):error='cancelled';break
                        if time.monotonic()-start>a.episode_timeout:error='worker_timeout';break
                    if error:runner.stop_owned(child)
                    result=json.loads((dest/'result.json').read_text()) if (dest/'result.json').exists() else {'status':'infrastructure_failure','error_code':'worker_exit'}
                    if error:result.update(status='cancelled' if error=='cancelled' else 'infrastructure_failure',error_code=error)
                    result.update(row,output=str(dest),worker=ident)
                finally:
                    if child.poll() is None:runner.stop_owned(child)
                    runner.release_process(child)
                with mutex:
                    rows.append(result);active.pop(str(gpu),None);dump(out/'rows.json',rows);dump(out/'summary.json',summarize(rows,planrows));dump(out/'paired.json',paired(rows));state()
                bad=bad+1 if result['status'] in TECH else 0
                if bad>=2:reason['stop']='technical_hold';stop.set();return
        def phase(selected,policies):
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                fs=[pool.submit(lane,g,[r for r in selected if r['gpu']==g],policies) for g in (0,1,6,7)]
                for f in concurrent.futures.as_completed(fs):
                    try:f.result()
                    except Exception:stop.set();raise
        pilot=[next(r for r in planrows if r['gpu']==g and r['arm']==arm)
               for g,arm in ((0,'native'),(1,'fixed'),(6,'fixed'),(7,'native'))]
        done={r['trial_id'] for r in rows}
        remaining_pilot=[r for r in pilot if r['trial_id'] not in done]
        if remaining_pilot:phase(remaining_pilot,{'fixed':out/'policies/fixed.json'})
        if stop.is_set():status=reason.get('stop','cancelled');return
        if any(r['status'] in TECH for r in rows):status='pilot_technical_hold';return
        start=time.monotonic()
        while not (out/'learning/report.json').exists():
            state('waiting_learning_gate')
            if (out/'learning/failure.json').exists() or learning.poll() is not None:raise RuntimeError('learning_failed')
            if time.monotonic()-start>14400:raise RuntimeError('learning_wait_timeout')
            if stop.wait(5):status='cancelled';return
        report=json.loads((out/'learning/report.json').read_text())
        if report['status']!='accepted' or report.get('promotions',0)<1:status='no_accepted_improvement';return
        candidate=load(out/'learning/accepted-policy.json')
        if digest(candidate)==digest(BASE_POLICY):raise RuntimeError('unchanged_evolved_policy')
        dump(out/'policies/evolved.json',candidate);dump(out/'policy-freeze.json',{'base':digest(BASE_POLICY),'evolved':digest(candidate),'learning_report_sha256':sha(out/'learning/report.json')})
        if a.resume:runner.acquire(state)
        done={r['trial_id'] for r in rows};phase([r for r in planrows if r['trial_id'] not in done],{'fixed':out/'policies/fixed.json','evolved':out/'policies/evolved.json'})
        status='completed' if len(rows)==len(planrows) else reason.get('stop','incomplete')
    except Exception as exc:
        dump(out/'queue-failure.json',{'type':type(exc).__name__,'code':str(exc) if str(exc) in ('learning_failed','learning_wait_timeout','unchanged_evolved_policy','source_changed') else 'inspect_structured_outputs'});status='failed'
    finally:
        runner.close()
        if learning and learning.poll() is None:stop_group(learning)
        dump(out/'report.json',{'status':status,'terminal':len(rows),'planned':len(planrows),'summary':summarize(rows,planrows),'pairs':paired(rows),
            'pending':[r['trial_id'] for r in planrows if r['trial_id'] not in {x['trial_id'] for x in rows}]})
        state(status)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('output','orders','qualification','reverse'):p.add_argument('--'+name,required=True)
    p.add_argument('--resume');p.add_argument('--episode-timeout',type=int,default=10800);main(p.parse_args())
