"""Explicit one-time launch after account-level shutdown has been resolved."""
import json, os, subprocess, sys, time
from pathlib import Path
R=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(R/'code'))
from run_case import verify,write
PY='/data/songziying/paos-libero-20261023/migration/conda-envs/paos-agent/bin/python'

def active(unit):
    return subprocess.run(['systemctl','--user','is-active','--quiet',unit]).returncode==0
def start(unit,log,args):
    subprocess.run(['systemd-run','--user','--unit='+unit,'--property=Restart=no',
        '--property=KillMode=mixed','--property=TimeoutStopSec=70',
        '--property=WorkingDirectory='+str(R/'code'),'--property=StandardOutput=append:'+str(log),
        '--property=StandardError=append:'+str(log),PY,'-u',*args],check=True)

def main():
    m=verify(R)
    if (R/'dispatch').exists() or (R/'pipeline-launch.json').exists():
        raise RuntimeError('previous_experiment_requires_audit_no_automatic_replay')
    if any(active(f'paos-libero-rsi-policy-gpu{g}.service') for g in m['gpus']):
        raise RuntimeError('existing_policy_service_requires_audit')
    prior=R/'policy-services'
    if prior.exists():
        for p in prior.glob('gpu*/identity.json'):
            row=json.loads(p.read_text())
            for key in ('supervisor','policy'):
                rec=row.get(key)
                if not rec:continue
                proc=Path('/proc')/str(rec['pid'])/'stat'
                if proc.exists() and proc.read_text().rsplit(')',1)[1].split()[19]==rec['start_ticks']:
                    raise RuntimeError('prior_owned_process_still_running')
        archive=R/'service-startup-history'/str(time.time_ns());archive.mkdir(parents=True)
        prior.rename(archive/'policy-services')
        for name in ('policy-services.json','user-manager-shutdown.log'):
            if (R/name).exists():(R/name).rename(archive/name)
        write(archive/'transition.json',{'reason':'explicit launcher invocation; retain prior account-shutdown evidence',
            'previous_physical_cases':0,'automatic_retry':False})
    for gpu in m['gpus']:
        start(f'paos-libero-rsi-policy-gpu{gpu}',R/f'policy-supervisor-gpu{gpu}.log',
            [str(R/'code/policy_supervisor.py'),'--root',str(R),'--source',str(R/'source'),
             '--core',str(R/'paos-core'),'--gpu',str(gpu)])
    begin=time.monotonic()
    while True:
        states=[]
        for gpu in m['gpus']:
            p=R/'policy-services'/f'gpu{gpu}'/'status.json'
            if p.exists():states.append(json.loads(p.read_text()))
        if any(x['state'] in ('failed','exited','stopped','stopped_before_start') for x in states):
            raise RuntimeError('policy_service_stopped_see_original_events_no_retry')
        if len(states)==len(m['gpus']) and all(x['state']=='ready' for x in states):break
        if time.monotonic()-begin>930:raise RuntimeError('policy_readiness_timeout_no_retry')
        time.sleep(2)
    write(R/'policy-services.json',dict(schema='paos-policy-services-v1',all_ready=True,
        status='ready',services=states,physical_cases_started=0,updated_unix=time.time(),automatic_retry=False))
    start('paos-libero-rsi-pipeline',R/'pipeline-service.log',[str(R/'code/pipeline.py')])
    write(R/'pipeline-launch.json',dict(time=time.time(),unit='paos-libero-rsi-pipeline.service',
        registration_sha256=(R/'registration.sha256').read_text().strip(),automatic_retry=False))
    print('Registered LIBERO development / automatic RSI / frozen evaluation pipeline launched.')

if __name__=='__main__':main()
