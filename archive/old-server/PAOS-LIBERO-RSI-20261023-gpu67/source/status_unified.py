"""Structured status only; no exception log or credential content."""
import json
from pathlib import Path
from collections import Counter
from durable_queue import read
from physical_runner import same_process

p=read('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/portable-runtime-20261023/paos/qwen-deploy/latest-memrsi-stream-v1_6r2.json')
if not p:
    print(json.dumps({'status':'not_started'}));raise SystemExit()
out=Path(p['result'])
print(json.dumps({'coordinator_alive':same_process(p['coordinator']),
    'report':read(out/'report.json'),'result':str(out)}))
for arm in ('native','fixed','evolved'):
    folder=out/arm;progress=read(folder/'progress.json',{});rows=read(folder/'evaluation/rows.json',[])
    active=[]
    for gpu,w in progress.get('active',{}).items():
        q=read(Path(w['output'])/'progress.json',{})
        active.append(dict(gpu=gpu,trial=w['trial_id'],alive=same_process(w['worker']),phase=q.get('phase'),session=q.get('session'),network_wait=read(Path(w['output'])/'transport-wait.json',{})))
    dev=[r for p in sorted((folder/'learning').glob('round-*/physical/rows.json')) for r in read(p,[])]
    print(json.dumps(dict(arm=arm,phase=progress.get('status'),active=active,
        terminal=len(rows),statuses=dict(Counter(r['status'] for r in rows)),
        development_terminal=len(dev),development_statuses=dict(Counter(r['status'] for r in dev)),
        learning=read(folder/'learning/progress.json'),report=read(folder/'report.json'))))
