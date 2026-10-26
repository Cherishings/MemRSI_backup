from pathlib import Path
import json,time,os
b=Path('/data/songziying/paos-libero-20261023')
a=json.loads((b/'development-launch.json').read_text());p=Path('/proc')/str(a['pid'])/'cmdline';out=Path(a['job']['output'])
def read(p):return json.loads(p.read_text()) if p.exists() else None
v=read(out/'result.json') or read(out/'progress.json') or {}
print(json.dumps({'time':time.time(),'gateway':read(b/'gateway-check.json'),'physical_acceptance':read(b/'qualification/physical-result.json'),'development':{'pid':a['pid'],'alive':p.exists() and str(b).encode() in p.read_bytes(),'condition':a['job']['condition_id'],'initialized_scenes':len(list(out.glob('*/physical/initial.json'))),'status':v.get('status'),'phase':v.get('phase'),'sessions_completed':v.get('sessions_completed'),'physical_executions':len(v.get('physical_executions',[])),'model_calls':read(out/'calls.json'),'error_code':v.get('error_code')}},indent=2))
