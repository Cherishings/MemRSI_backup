"""Read-only status; no credentials or raw exception logs."""
import json,time
from pathlib import Path
from run_queue import BASE,identity

def read(path):return json.loads(path.read_text()) if path.exists() else None

def process(record):
    if not record:return None
    try:live=identity(record['pid']);same=live['start_ticks']==str(record['start_ticks'])
    except (FileNotFoundError,ProcessLookupError):same=False
    return dict(record,identity_matches=same)

def main():
    pointer=read(BASE/'qwen-deploy/latest-memrsi-feedback.json')
    if not pointer:print(json.dumps({'status':'not_launched'}));return
    root=Path(pointer['result']);progress=read(root/'progress.json') or {};learning=read(root/'learning/progress.json')
    active=[]
    for gpu,row in progress.get('active',{}).items():
        d=Path(row['output']);p=read(d/'progress.json') or {};calls=read(d/'calls.json') or {}
        active.append({'gpu':int(gpu),'trial':row['trial_id'],'arm':row['arm'],'worker':process(row.get('worker')),
          'phase':p.get('phase'),'session':p.get('session'),'sessions_completed':p.get('sessions_completed'),
          'physical_segments':len(p.get('physical_executions',[])),
          'reached':p.get('reached_checkpoints'),'correct':p.get('correct_checkpoints'),'model_calls':calls.get('calls'),
          'last_progress_unix':p.get('updated_unix')})
    policies=[dict(read(p),identity_matches=process(read(p))['identity_matches']) for p in (root/'gpu-workers').glob('policy-*.identity.json')]
    probes=[]
    for p in (root/'learning').glob('**/result.json'):
        r=read(p);probes.append({k:r.get(k) for k in ('fixture','status','correct','error_code')})
    print(json.dumps({'checked_unix':time.time(),'result':str(root),'coordinator':process(pointer['coordinator']),
       'status':progress.get('status'),'planned':progress.get('planned'),'terminal':progress.get('terminal'),
       'policies':policies,'active':active,'learning':learning,'learning_process':process(read(root/'learning-process.json')),
       'probe_results':probes,'summary':read(root/'summary.json'),'queue_failure':read(root/'queue-failure.json'),
       'learning_failure':read(root/'learning/failure.json')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
