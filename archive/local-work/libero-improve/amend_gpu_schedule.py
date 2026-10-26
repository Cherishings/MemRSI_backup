"""Pre-outcome scheduling amendment: preserve all scientific inputs and evidence."""
import hashlib, json, shutil, sys, time
from pathlib import Path
R=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023')
sys.path.insert(0,str(R/'code'))
from run_case import verify,write
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
m=verify(R)
assert not (R/'dispatch').exists() and not (R/'pipeline-launch.json').exists()
assert not (R/'development').exists() and not (R/'final').exists()
assert m['gpus']==[2,3,4,6,7]
prior_sha=sha(R/'registration.json')
folder=R/'registration-history'/str(time.time_ns());folder.mkdir(parents=True)
for name in ('registration.json','registration.sha256'):
    shutil.copy2(R/name,folder/name)
changes={
 'code/pipeline.py':("m['gpus'][len(jobs)%5]","m['gpus'][len(jobs)%len(m['gpus'])]"),
 'code/launch.py':("len(states)==5","len(states)==len(m['gpus'])"),
}
details={}
for name,(old,new) in changes.items():
    p=R/name;text=p.read_text();assert text.count(old)==1
    shutil.copy2(p,folder/p.name)
    p.write_text(text.replace(old,new))
    compile(p.read_text(),str(p),'exec')
    details[name]={'old_sha256':m['frozen_files'][name],'new_sha256':sha(p),'old':old,'new':new}
    m['frozen_files'][name]=sha(p)
m['gpus']=[2,4,6,7]
amendment={
 'time':time.time(),'previous_registration_sha256':prior_sha,
 'reason':'GPU 3 occupied by unrelated actworld perf_worker PID 2183861; never stop unrelated jobs',
 'previous_gpus':[2,3,4,6,7],'gpus':[2,4,6,7],
 'physical_cases_started':0,'model_method_scoring_data_budget_changed':False,
 'code_changes':details,'previous_registration':str(folder/'registration.json'),
}
m.setdefault('administrative_amendments',[]).append(amendment)
write(R/'registration.json',m)
(R/'registration.sha256').write_text(sha(R/'registration.json')+'\n')
amendment['registration_sha256']=sha(R/'registration.json')
write(folder/'amendment.json',amendment)
verify(R)
print(json.dumps(amendment))
