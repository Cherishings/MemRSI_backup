import pathlib,json,hashlib,time,os,sys,subprocess
b=pathlib.Path('/data/songziying/paos-libero-20261023');r=b/'study-contract-validation-v1'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
q=read(r/'queue-status.json');assert q['phase']=='blocked'
assert not (pathlib.Path('/proc')/str(q['pid'])).exists()
out=pathlib.Path(q['job']['output']);result=read(out/'result.json')
if result['status']=='execution_failure':
 last=result['physical_executions'][-1]['result'];assert len(last['attempts'])==3 and all(not a['native_goal_reached'] for a in last['attempts'])
 category='physical_execution_failure';evidence={'attempts':last['attempts'],'state_sha256':last['after']['state_sha256']}
else:
 assert result['error_code']=='native_session_archival_failed'
 rows=[json.loads(l) for l in (out/'model-trace.jsonl').read_text().splitlines()];last=rows[-1]['response']
 assert last['finish_reason']=='stop' and not last.get('tool_calls')
 category='method_archive_protocol_failure';evidence={'trace_sha256':sha(out/'model-trace.jsonl'),'last_finish_reason':'stop','last_tool_calls':0,'raw_status_retained':result['status']}
record=r/f"continuation-{q['job']['arm']}-0804.json";assert not record.exists()
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
reg={'time':time.time(),'classification':category,'evidence':evidence,'raw_result':str(out/'result.json'),'raw_result_sha256':sha(out/'result.json'),
'completed_results':{str(p):sha(p) for p in (r/'development').glob('*/*/result.json')},'previous_queue':q,
'retry':False,'policy_budget_physics_changed':False,'registration_sha256':sha(r/'registration.json'),'schedule_sha256':sha(r/'development-schedule.json')}
record.write_text(json.dumps(reg,indent=2))
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
os.environ['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),os.environ.get('PYTHONPATH','')])
with (r/f"queue-continuation-{q['job']['arm']}-0804.log").open('x') as f:p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=f,stderr=f,env=os.environ.copy(),start_new_session=True)
(r/f"continuation-{q['job']['arm']}-0804-launch.json").write_text(json.dumps({'pid':p.pid,'time':time.time()}));print(json.dumps({'pid':p.pid,'classification':category,'preserved':len(reg['completed_results'])}))
