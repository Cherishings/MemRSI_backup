import json, pathlib, shutil, hashlib, sys, os, signal, subprocess, time
b=pathlib.Path('/data/songziying/paos-libero-20261023')
old=b/'study-scope-v3'; r=b/'study-scope-v3-technical1'
assert not r.exists(), 'Never duplicate technical replacement'
assert json.loads((b/'active-study.json').read_text())['root']==str(old)
allocation=json.loads((old/'allocation.json').read_text());node=str(allocation['node'])
condition,arm={'107':('hEDABC-v1-i0','gu_parent'),'108':('hEADCB-v1-i1','native')}[node]
original=old/'development'/condition/arm/'result.json'
assert json.loads(original.read_text())['status']=='infrastructure_failure'
schedule=json.loads((old/'development-schedule.json').read_text())
job=next(j for j in schedule if j['condition_id']==condition and j['arm']==arm)
assert condition in allocation['allowed_condition_ids']
r.mkdir()
for name in ('code','source','policies'):
 shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to(old/'paos-core',target_is_directory=True)
for name in ('orders.json','budget.json','parent-policy.json','allocation.json','env.sh'):
 shutil.copy2(old/name,r/name)
for p in list((r/'code').rglob('*.py'))+list((r/'source').glob('*.py'))+[r/'env.sh']:
 p.write_text(p.read_text().replace(str(old),str(r)))
job=dict(job,output=str(r/'development'/condition/arm))
(r/'development-schedule.json').write_text(json.dumps([job],indent=2)+'\n')
for name in ('jobs','logs'):(r/name).mkdir()
record={'kind':'one_time_infrastructure_replacement','registered_at':time.time(),
 'original_result':str(original),'original_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
 'replacement_job':job,'attempt_limit':1,'method_and_budgets_unchanged':True,
 'original_cost_retained':True,'original_not_a_method_failure':True,
 'comparison_block':'scope-v3','on_any_terminal_result':'retain; no automatic second replacement',
 'remaining_v3_schedule':'deferred pending completed first-condition comparisons and manual-parent revision decision'}
(r/'technical-replacement.json').write_text(json.dumps(record,indent=2)+'\n')
m=json.loads((old/'registration.json').read_text());m['registered_at']=time.time()
m['administrative_amendments'].append(record)
for name in m['frozen_files']:m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
m['frozen_files']['technical-replacement.json']=hashlib.sha256((r/'technical-replacement.json').read_bytes()).hexdigest()
(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n')
(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
assert (r/'parent-policy.json').read_bytes()==(old/'parent-policy.json').read_bytes()
assert (r/'budget.json').read_bytes()==(old/'budget.json').read_bytes()
q=json.loads((old/'queue-status.json').read_text());pid=q['pid']
assert q['phase']=='running'
assert str(old/'code/queue_v2.py').encode() in pathlib.Path(f'/proc/{pid}/cmdline').read_bytes()
os.kill(pid,signal.SIGSTOP)
try:
 # Read once more after stopping dispatch so the currently running case is authoritative.
 q=json.loads((old/'queue-status.json').read_text());assert q['pid']==pid and q['phase']=='running'
 h={'previous_queue_pid':pid,'previous_job':q['job'],'previous_root':str(old),
    'phase':'waiting_for_current_case','created':time.time()}
 (r/'handoff.json').write_text(json.dumps(h,indent=2))
 env=os.environ.copy()
 env['PYTHONPATH']=env.get('PYTHONPATH','').replace(str(old),str(r))
 with (r/'handoff.log').open('x') as log:
  p=subprocess.Popen([sys.executable,str(b/'technical1-incoming/handoff.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=env)
 (r/'handoff-pid.json').write_text(json.dumps({'pid':p.pid}))
 print(json.dumps({'root':str(r),'replacement':job,'waiting_for':q['job'],'handoff_pid':p.pid}))
except BaseException:
 os.kill(pid,signal.SIGCONT)
 raise
