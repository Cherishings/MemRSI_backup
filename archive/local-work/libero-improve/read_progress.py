"""Read-only operational evidence, separate from experimental scoring."""
import json, time
from pathlib import Path
R=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023')
def read(p):
    try:return json.loads(p.read_text())
    except (FileNotFoundError,json.JSONDecodeError):return None
m=read(R/'registration.json')
out={'observed_unix':time.time(),'registration_sha256':(R/'registration.sha256').read_text().strip(),
     'status':read(R/'status.json'),'policies':{},'cases':[]}
for g in m['gpus']:
    s=read(R/'policy-services'/f'gpu{g}'/'status.json') or {}
    out['policies'][str(g)]={k:s.get(k) for k in ('state','reason','startup_elapsed_seconds')}
for phase in ('development/train','development/validation','final'):
    folder=R/phase
    if not folder.exists():continue
    for d in sorted(folder.glob('h*/*')):
        if not d.is_dir():continue
        result=read(d/'result.json')
        row={'path':str(d.relative_to(R)),'progress':read(d/'progress.json')}
        if result:
            row['result']={k:result.get(k) for k in ('status','registered_failure_class','error_code',
              'sessions_completed','reached_checkpoints','answered_checkpoints','correct_checkpoints',
              'partial_successes','recovery_successes','rollovers','registered_arm','reference_only')}
            row['physical_executions']=len(result.get('physical_executions',[]))
        physical=[]
        for p in sorted(d.glob('*/physical/execution-*.json')):
            e=read(p) or {}
            physical.append({'path':str(p.relative_to(d)),
                **{k:e.get(k) for k in ('success','native_task_complete','components_after')},
                'after':{k:e.get('after',{}).get(k) for k in ('steps','policy_calls','reset_count','state_sha256','action_sha256')}})
        row['executions']=physical
        row['sampling_files']=[{'path':str(p.relative_to(d)),'bytes':p.stat().st_size}
            for p in sorted(d.glob('*/physical/policy-sampling.jsonl'))]
        out['cases'].append(row)
print(json.dumps(out,ensure_ascii=False))
