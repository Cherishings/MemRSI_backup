"""Record externally interrupted jobs without changing results or retrying them."""
import json, os, time
from pathlib import Path
R=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023')
import sys
sys.path.insert(0,str(R/'code'))
from run_case import verify,write
verify(R)
launch=json.loads((R/'pipeline-launch.json').read_text())
assert not Path('/proc',str(launch['pid'])).exists(),'pipeline_still_exists'
prior=json.loads((R/'status.json').read_text())
cases=[]
for lane in sorted(R.glob('lane-gpu*.json')):
    value=json.loads(lane.read_text())
    assert not Path('/proc',str(value['pid'])).exists(),'case_still_exists'
    out=Path(value['job']['output'])
    result=out/'result.json'
    progress=out/'progress.json'
    cases.append({'gpu':value['job']['gpu'],'condition_id':value['job']['condition_id'],
       'output':str(out),'pid':value['pid'],'process_alive':False,
       'result_exists':result.exists(),
       'last_progress':json.loads(progress.read_text()) if progress.exists() else None})
record={'phase':'blocked','reason':'account_wide_user_manager_shutdown_observed',
 'observed_unix':time.time(),'shutdown_local_time':'2026-10-23T18:19:47+08:00',
 'new_manager_local_time':'2026-10-23T18:19:58+08:00',
 'cause_of_shutdown':'unknown; requires system-level logs not accessible to this account',
 'registration_sha256':(R/'registration.sha256').read_text().strip(),
 'running_experiment_processes':0,'interrupted_cases':cases,
 'completed_physical_episodes':sum(x['result_exists'] for x in cases),
 'automatic_retry':False,'scores_synthesized':False,
 'resume_requirement':'Audit technical interruption and preserve all partial evidence before resuming; no method or scoring edits.'}
assert record['completed_physical_episodes']==0
folder=R/'runtime-control'/('interruption-'+str(time.time_ns()))
write(folder/'last-controller-status.json',prior)
write(folder/'observed-interruption.json',record)
write(R/'status.json',record)
print(json.dumps(record,ensure_ascii=False))
