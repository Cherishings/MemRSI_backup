import json,pathlib,hashlib,sys,os,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023');r=b/'study-contract-validation-v1'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
q=read(r/'queue-status.json');assert q['phase']=='blocked' and q['reason']=='execution_failure'
assert not (pathlib.Path('/proc')/str(q['pid'])).exists()
out=pathlib.Path(q['job']['output']);result=read(out/'result.json')
last=result['physical_executions'][-1]['result']
assert result['status']=='execution_failure' and not last['success']
assert len(last['attempts'])==3 and all(not a['native_goal_reached'] for a in last['attempts'])
record=r/'execution-failure-continue-20261025.json';assert not record.exists()
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
completed={str(p):sha(p) for p in (r/'development').glob('*/*/result.json')}
reg={'time':time.time(),'reason':'Observed native physical failure after registered attempts, no infrastructure exception; preserve and continue unexecuted jobs',
'failed_result':str(out/'result.json'),'failed_result_sha256':sha(out/'result.json'),'completed_results':completed,
'previous_queue':q,'retry_failed_case':False,'physical_policy_changed':False,'method_changed':False,
'budget_changed':False,'registration_sha256':sha(r/'registration.json'),'schedule_sha256':sha(r/'development-schedule.json')}
record.write_text(json.dumps(reg,indent=2))
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
os.environ['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),os.environ.get('PYTHONPATH','')])
with (r/'queue-continuation.log').open('x') as f:p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=f,stderr=f,env=os.environ.copy(),start_new_session=True)
(r/'queue-continuation-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}));print(json.dumps({'pid':p.pid,'preserved_results':len(completed)}))
