#!/usr/bin/env bash
set -euo pipefail
ssh xi 'python3 -' <<'PY'
import json, pathlib
p=pathlib.Path('/data/stormlab/xi/paos/qwen-deploy/latest-twenty-experiment.json')
if not p.exists():
    print('20会话正式队列尚未创建。');raise SystemExit
pointer=json.loads(p.read_text());root=pathlib.Path(pointer['result']);print('结果目录:',root)
for name in ['budget.json','progress.json','summary.json','queue-failure.json']:
    f=root/name
    if f.exists():print(name, json.dumps(json.loads(f.read_text()),ensure_ascii=False,indent=2))
for f in root.glob('evaluation/*/*/progress.json'):
    x=json.loads(f.read_text())
    if x.get('status')=='running':print('当前案例:',str(f.parent.relative_to(root)),{k:x.get(k) for k in ['sessions_completed','phase','session','reached_checkpoints','correct_checkpoints']})
PY
