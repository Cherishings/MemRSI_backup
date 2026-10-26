#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 1 ]]; then
  echo "Usage: bash check.sh /absolute/path/to/physical-output" >&2
  exit 2
fi
python3 - "$1" <<'PY'
import json
from pathlib import Path
import sys

root=Path(sys.argv[1])
def read(name):
    p=root/name
    return json.loads(p.read_text()) if p.exists() else None
def alive(record):
    if not record:return False
    try:
        fields=Path('/proc/%d/stat'%record['pid']).read_text().rsplit(')',1)[1].split()
        return fields[19]==str(record['start_ticks']) and fields[0]!='Z'
    except (FileNotFoundError,ProcessLookupError):return False
p=read('progress.json') or {}
out={'directory':str(root),'status':p.get('status'),'terminal':p.get('terminal',0),
     'planned':p.get('planned',48),'coordinator_alive':alive(read('coordinator.json')),
     'updated_unix':p.get('updated_unix'),'arms':read('summary.json'),
     'policies':read('frozen-policies.json'),'active':[]}
for gpu,row in p.get('active',{}).items():
    item={k:row.get(k) for k in ('status','phase','trial_id','output')}
    item.update(gpu=gpu,worker_alive=alive(row.get('worker')))
    trial=Path(row.get('output',''))/'progress.json'
    if row.get('output') and trial.exists():
        data=json.loads(trial.read_text())
        item['trial_progress']={k:data.get(k) for k in ('phase','stage','order_index','arrived_checkpoint','correct_checkpoint','updated_unix')}
    out['active'].append(item)
out['policies_alive']={str(g):alive(read('policy-gpu%d.identity.json'%g)) for g in (0,1)}
print(json.dumps(out,ensure_ascii=False,indent=2))
PY
