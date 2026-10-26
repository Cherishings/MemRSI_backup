"""Read-only, safe result/status summary; no exception text or credentials."""
import json
from pathlib import Path
from collections import Counter
from durable_queue import read
from physical_runner import same_process
BASE=Path('/data/songziying/paos-libero-20261023/migration/portable-runtime-20261023/paos/qwen-deploy')
for name in ('memrsi-baseline-012r1','memrsi-stream-v1_6'):
 p=read(BASE/('latest-'+name+'.json'))
 if not p:print(json.dumps({'name':name,'status':'not_started'}));continue
 out=Path(p['result']);progress=read(out/'progress.json',{});active=[]
 for gpu,w in progress.get('active',{}).items():
  q=read(Path(w['output'])/'progress.json',{})
  active.append(dict(gpu=gpu,trial=w['trial_id'],phase=q.get('phase'),session=q.get('session'),alive=same_process(w['worker'])))
 batches={}
 for batch in ('transfer','comparison-recovery','evaluation'):
  rows=read(out/batch/'rows.json',[])
  batches[batch]={'terminal':len(rows),'statuses':dict(Counter((r['arm']+':'+r['status']) for r in rows))}
 print(json.dumps(dict(name=name,alive=same_process(p['coordinator']),phase=progress.get('status'),active=active,
   batches=batches,learning=read(out/'learning/progress.json'),report_status=read(out/'report.json',{}).get('status'),result=str(out)),ensure_ascii=False))
