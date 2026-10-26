"""Finite LIBERO development -> automatic G/U learning -> frozen comparisons."""
import fcntl, hashlib, json, os, signal, socket, subprocess, sys, time, traceback
from pathlib import Path
R=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(R/'code'),str(R/'code/runtime')]
from run_case import write,verify
from libero_runtime import lane_env
PY='/data/songziying/paos-libero-20261023/migration/conda-envs/paos-agent/bin/python'
children=[]; stopping=False
def stop(signum,*_):
    global stopping
    stopping=True;write(R/'stop-request.json',{'signal':signum,'time':time.time()})
for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def status(phase,**kw):write(R/'status.json',dict(phase=phase,time=time.time(),**kw))
def check_stop():
    if stopping or (R/'STOP').exists():raise RuntimeError('requested_stop')
    if time.monotonic()-START>m['total_timeout_seconds']:raise RuntimeError('registered_total_timeout')
def cleanup():
    for p in children:
        try:os.killpg(p.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    until=time.monotonic()+35
    while any(p.poll() is None for p in children) and time.monotonic()<until:time.sleep(.5)
    for p in children:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    # These exact named units were created only for this study. Release its GPU
    # leases and models when the finite run completes or pauses on a real fault.
    try:
        subprocess.run(['systemctl','--user','stop',*[f'paos-libero-rsi-policy-gpu{g}.service' for g in (6,7)]],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=80,check=False)
    except subprocess.TimeoutExpired:
        write(R/'cleanup-incomplete.json',{'reason':'systemd_stop_timeout','time':time.time()})
def spawn(cmd,log,gpu):
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('xb') as f:p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=f,stderr=f,
        start_new_session=True,env=lane_env(gpu,'agent'))
    children.append(p);return p
def make_jobs(conditions,policies,phase):
    jobs=[]
    for n,c in enumerate(conditions):
        # Rotate treatment order across histories and lanes, with no result input.
        arms=list(policies);offset=n%len(arms);arms=arms[offset:]+arms[:offset]
        for arm in arms:
            policy=policies[arm]
            jobs.append(dict(c,arm=arm,phase=phase,gpu=m['gpus'][len(jobs)%len(m['gpus'])],
                policy=str(policy) if policy else None,policy_file_sha256=sha(policy) if policy else None,
                output=str(R/phase/c['condition_id']/arm)))
    return jobs
def batch(jobs,phase):
    verify(R);queue={g:[j for j in jobs if j['gpu']==g] for g in m['gpus']};active={};completed=[]
    folder=R/'dispatch'/phase;folder.mkdir(parents=True,exist_ok=False)
    write(folder/'manifest.json',jobs)
    for n,j in enumerate(jobs):
        j['dispatch_file']=str(folder/f'job-{n:04d}.json');write(Path(j['dispatch_file']),j)
    while any(queue.values()) or active:
        check_stop()
        for gpu in m['gpus']:
            if gpu not in active and queue[gpu]:
                j=queue[gpu].pop(0);p=spawn([PY,str(R/'code/run_case.py'),'--root',str(R),'--job',j['dispatch_file']],
                    Path(j['dispatch_file']).with_suffix('.log'),gpu)
                active[gpu]=(p,j,time.monotonic())
                write(R/f'lane-gpu{gpu}.json',dict(phase=phase,job=j,pid=p.pid,started=time.time()))
        for gpu,(p,j,started) in list(active.items()):
            if time.monotonic()-started>m['episode_timeout_seconds']:raise RuntimeError('episode_timeout:'+j['output'])
            code=p.poll()
            if code is None:continue
            if code!=0:raise RuntimeError('episode_infrastructure_failure:'+j['output']+':exit='+str(code))
            result=json.loads((Path(j['output'])/'result.json').read_text())
            if result.get('registered_arm')!=j['arm']:raise RuntimeError('unregistered_result')
            completed.append(dict(j,result=result));active.pop(gpu);children.remove(p)
            write(R/f'lane-gpu{gpu}.json',dict(phase='between_cases',last_output=j['output'],time=time.time()))
        status(phase,completed=len(completed),planned=len(jobs),active={str(g):x[1]['output'] for g,x in active.items()})
        if active:time.sleep(10)
    write(R/phase/'completed-results.json',completed);return completed
def learning():
    args=[PY,str(R/'code/learn.py'),'--root',str(R),'--source',str(R/'source'),'--core',str(R/'paos-core'),
        '--train-manifest',str(R/'development/training-sources.json'),
        '--validation-manifest',str(R/'development/validation-sources.json'),
        '--parent-policy',str(R/'parent-policy.json'),'--budget',str(R/'budget.json')]
    p=spawn(args,R/'learning-controller.log',m['gpus'][0]);status('automatic_G_U_learning',max_proposals=2)
    while p.poll() is None:
        check_stop();time.sleep(10)
    if p.returncode:raise RuntimeError('automatic_learning_blocked:exit='+str(p.returncode))
    children.remove(p)
    report=R/'learning/report.json';selected=R/'learning/selected-policy.json'
    if not report.exists() or not selected.exists():raise RuntimeError('learning_freeze_missing')
    return json.loads(selected.read_text())
def freeze_final(learned):
    import method
    parent=json.loads((R/'parent-policy.json').read_text());policies={};aliases={};seen={};hashes={}
    dest=R/'final-policies';dest.mkdir(exist_ok=False)
    for arm in m['final_arms']:
        value=method.policy_for(parent,learned,arm)
        canonical=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
        hashes[arm]=canonical
        if canonical in seen:aliases[arm]=seen[canonical];continue
        seen[canonical]=arm
        if value is None:policies[arm]=None
        else:
            path=dest/(arm+'.json');write(path,value);policies[arm]=path
    frozen=dict(time=time.time(),registration_sha256=(R/'registration.sha256').read_text().strip(),
        parent_file_sha256=sha(R/'parent-policy.json'),selected_file_sha256=sha(R/'learning/selected-policy.json'),
        learning_report_sha256=sha(R/'learning/report.json'),canonical_policy_hashes=hashes,aliases=aliases,
        conditions=m['test_conditions'],distinct_arms=list(policies),planned_episodes=len(policies)*48,
        no_final_results_seen=not (R/'final').exists(),
        changed_operators=[k for k in ('guidance','update') if parent[k]!=learned[k]])
    assert frozen['no_final_results_seen']
    write(R/'final-registration.json',frozen)
    (R/'final-registration.sha256').write_text(sha(R/'final-registration.json')+'\n')
    return policies
def main():
    global START,m
    START=time.monotonic();m=verify(R)
    os.environ.update(PAOS_LIBERO_SOURCE=str(R/'source'),PAOS_CORE_ROOT=str(R/'paos-core'))
    for gpu in m['gpus']:
        with socket.create_connection(('127.0.0.1',20500+gpu),3):pass
    status('development_starting',training=8,validation=4,gpus=m['gpus'])
    for split,key in [('train','training_conditions'),('validation','validation_conditions')]:
        rows=batch(make_jobs(m[key],{'gu_parent':R/'parent-policy.json'},'development/'+split),'development/'+split)
        name='training-sources.json' if split=='train' else 'validation-sources.json'
        write(R/'development'/name,[{'id':r['condition_id'],'output':r['output']} for r in sorted(rows,key=lambda x:x['condition_id'])])
    selected=learning();verify(R);policies=freeze_final(selected)
    rows=batch(make_jobs(m['test_conditions'],policies,'final'),'final')
    import analyze
    analyze.main(R)
    summary={arm:{'successes':sum(x['result']['status']=='success' for x in rows if x['arm']==arm),
                  'planned':48} for arm in policies}
    status('completed',completed=len(rows),planned=len(rows),summary=summary,
        final_registration_sha256=sha(R/'final-registration.json'))
if __name__=='__main__':
    owned=False
    try:
        with (R/'pipeline.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);owned=True;main()
    except Exception as e:
        if owned:status('blocked',error_type=type(e).__name__,reason=str(e)[:500],automatic_retry=False)
        traceback.print_exc();sys.exit(2)
    finally:
        if owned:cleanup()
