"""Run the already registered study under a live SSH terminal, without systemd."""
import fcntl, hashlib, json, os, signal, subprocess, sys, time
from pathlib import Path
R=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023-gpu67')
sys.path.insert(0,str(R/'code'))
from run_case import verify,write
PY='/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/conda-envs/paos-agent/bin/python'
processes=[];stopped=None
def stop(signum,*_):
    global stopped
    stopped=signum
for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,stop)
def same(record):
    p=Path('/proc')/str(record['pid'])/'stat'
    return p.exists() and p.read_text().rsplit(')',1)[1].split()[19]==record['start_ticks']
def spawn(args,log):
    with log.open('xb') as f:p=subprocess.Popen([PY,'-u',*args],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
    processes.append(p);return p
def main():
    m=verify(R)
    if (R/'dispatch').exists() or (R/'pipeline-launch.json').exists():raise RuntimeError('existing_experiment_requires_audit')
    prior=R/'policy-services'
    if prior.exists():
        for path in prior.glob('gpu*/identity.json'):
            d=json.loads(path.read_text())
            if any(same(d[k]) for k in ('supervisor','policy') if k in d):raise RuntimeError('prior_policy_process_running')
        archive=R/'service-startup-history'/str(time.time_ns());archive.mkdir(parents=True)
        prior.rename(archive/'policy-services')
        if (R/'policy-services.json').exists():(R/'policy-services.json').rename(archive/'policy-services.json')
    run=R/'runtime-control'/str(time.time_ns());run.mkdir(parents=True)
    write(run/'hosting.json',{'hosting':'live SSH tty','pid':os.getpid(),'time':time.time(),
        'reason':'user requested continuation after repeated user-manager shutdowns',
        'registration_sha256':(R/'registration.sha256').read_text().strip(),
        'method_and_scoring_changed':False,'automatic_retry':False,
        'policy_loading':'serial, one policy ready before the next',
        'orchestration_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    for gpu in m['gpus']:
        spawn([str(R/'code/policy_supervisor.py'),'--root',str(R),'--source',str(R/'source'),
               '--core',str(R/'paos-core'),'--gpu',str(gpu)],run/f'policy-supervisor-gpu{gpu}.log')
        began=time.monotonic();reported=0
        while True:
            if stopped is not None:raise RuntimeError('foreground_signal_'+str(stopped))
            if any(p.poll() is not None for p in processes):raise RuntimeError('policy_supervisor_exited')
            path=R/'policy-services'/f'gpu{gpu}'/'status.json'
            state=json.loads(path.read_text()) if path.exists() else {}
            if state.get('state')=='ready':
                print(json.dumps({'gpu_ready':gpu,'elapsed':time.monotonic()-began}),flush=True);break
            if time.monotonic()-began>930:raise RuntimeError('policy_readiness_timeout')
            if time.monotonic()-reported>=30:
                mem={x.split(':')[0]:x.split(':')[1].strip() for x in Path('/proc/meminfo').read_text().splitlines()}
                print(json.dumps({'phase':'serial_policy_loading','gpu':gpu,'state':state.get('state','pending'),
                    'memory_available':mem.get('MemAvailable')}),flush=True);reported=time.monotonic()
            time.sleep(2)
    start=time.monotonic();last=0
    while True:
        if stopped is not None:raise RuntimeError('foreground_signal_'+str(stopped))
        if any(p.poll() is not None for p in processes):raise RuntimeError('policy_supervisor_exited')
        states=[json.loads((R/'policy-services'/f'gpu{g}'/'status.json').read_text()) for g in m['gpus']]
        if len(states)==len(m['gpus']) and all(x['state']=='ready' for x in states):break
        if time.monotonic()-start>930:raise RuntimeError('policy_readiness_timeout')
        if time.monotonic()-last>=30:
            print(json.dumps({'phase':'loading_policies','states':{x['gpu']:x['state'] for x in states}}),flush=True);last=time.monotonic()
        time.sleep(2)
    write(R/'policy-services.json',{'all_ready':True,'hosting':'foreground SSH processes, legacy unit field unused',
        'services':states,'physical_cases_started':0,'automatic_retry':False})
    pipeline=spawn([str(R/'code/pipeline.py')],run/'pipeline.log')
    write(R/'pipeline-launch.json',{'time':time.time(),'pid':pipeline.pid,'hosting':'live SSH tty',
        'registration_sha256':(R/'registration.sha256').read_text().strip(),'runtime_control':str(run),'automatic_retry':False})
    print(f"All {len(m['gpus'])} policies ready. Registered LIBERO pipeline started.",flush=True)
    while pipeline.poll() is None:
        if stopped is not None:raise RuntimeError('foreground_signal_'+str(stopped))
        if any(p.poll() is not None for p in processes[:-1]):raise RuntimeError('policy_supervisor_exited')
        if time.monotonic()-last>=30:
            p=R/'status.json'
            if p.exists():print(p.read_text(),flush=True)
            last=time.monotonic()
        time.sleep(2)
    if pipeline.returncode:raise RuntimeError('pipeline_exit_'+str(pipeline.returncode))
    print('Registered pipeline completed.',flush=True)
def cleanup():
    for p in reversed(processes):
        if p.poll() is None:
            try:os.killpg(p.pid,signal.SIGTERM)
            except ProcessLookupError:pass
    until=time.monotonic()+50
    while any(p.poll() is None for p in processes) and time.monotonic()<until:time.sleep(.5)
    for path in (R/'policy-services').glob('gpu*/identity.json'):
        d=json.loads(path.read_text())
        for key in ('supervisor','policy'):
            rec=d.get(key)
            if rec and same(rec):
                try:os.killpg(rec.get('pgid',rec['pid']),signal.SIGKILL)
                except ProcessLookupError:pass
    for p in processes:
        if p.poll() is None:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
if __name__=='__main__':
    owned=False
    try:
        with (R/'foreground-runner.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);owned=True;main()
    except Exception as e:
        if owned:write(R/'foreground-blocked.json',{'time':time.time(),'error':str(e),'automatic_retry':False})
        raise
    finally:
        if owned:cleanup()
