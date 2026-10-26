#!/usr/bin/env bash
set -euo pipefail
ssh -o BatchMode=yes -o ConnectTimeout=15 -p 7001 ext_songzhiying@39.105.30.146 'python3 - <<'"'"'PY'"'"'
import json
from pathlib import Path
r=Path("/media/disks/disk1/share/ext_songzhiying/PAOS-validation-20261023")
for name in ("status.json","live-gu-probe/result.json","gpu-render-acceptance.json"):
 p=r/name
 print(name)
 print(json.dumps(json.loads(p.read_text()),ensure_ascii=False,indent=2) if p.exists() else "pending")
p=r/"gu-factorial/blocked.json"
if p.exists(): print("blocked:",p.read_text())
PY'
