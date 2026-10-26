"""New infrastructure attempt, preserving the interrupted registration and files."""
import hashlib,json,shutil,time
from pathlib import Path
OLD=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023')
R=OLD.with_name(OLD.name+'-gpu67')
assert not R.exists(),'new_attempt_already_exists'
old=json.loads((OLD/'registration.json').read_text())
for name,h in old['frozen_files'].items():
    assert hashlib.sha256((OLD/name).read_bytes()).hexdigest()==h,name
assert json.loads((OLD/'status.json').read_text())['running_experiment_processes']==0
R.mkdir()
for name in ('code','source','paos-core'):
    shutil.copytree(OLD/name,R/name,ignore=shutil.ignore_patterns('__pycache__'))
for name in ('orders.json','budget.json','parent-policy.json'):
    shutil.copy2(OLD/name,R/name)
p=R/'code/pipeline.py';s=p.read_text()
assert s.count("p=spawn(args,R/'learning-controller.log',2)")==1
s=s.replace("p=spawn(args,R/'learning-controller.log',2)","p=spawn(args,R/'learning-controller.log',m['gpus'][0])")
s=s.replace("for g in (2,3,4,6,7)","for g in (6,7)")
p.write_text(s);compile(s,str(p),'exec')
m=json.loads(json.dumps(old));m['gpus']=[6,7]
m['registered_at']=time.time()
m['administrative_amendments'].append({
 'time':time.time(),'reason':'User explicitly requests a new attempt on GPU 6 and 7 only after account-wide interruption',
 'previous_root':str(OLD),'previous_registration_sha256':(OLD/'registration.sha256').read_text().strip(),
 'previous_complete_episodes':0,'previous_interrupted_development_cases':4,
 'previous_outputs_preserved':True,'method_data_scoring_budgets_changed':False,
 'gpus':[6,7],'learning_process_lane':6,'automatic_retry':False})
m['frozen_files']['code/pipeline.py']=hashlib.sha256(p.read_bytes()).hexdigest()
(R/'registration.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
(R/'registration.sha256').write_text(hashlib.sha256((R/'registration.json').read_bytes()).hexdigest()+'\n')
(R/'runtime-control').mkdir()
wrapper=(OLD/'runtime-control/foreground_runner.py').read_text().replace(str(OLD),str(R))
(R/'runtime-control/foreground_runner.py').write_text(wrapper)
print(json.dumps({'root':str(R),'registration_sha256':(R/'registration.sha256').read_text().strip(),'gpus':m['gpus']}))
