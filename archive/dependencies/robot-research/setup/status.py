import json
from pathlib import Path
r=Path('/data/stormlab/xi/robot')
for name in ['twin','casa']:
 out={'platform':name}
 for label,filename in [('install',f'install-{name}.json'),('validation',f'ready-{name}.json')]:
  p=r/'setup'/filename
  out[label]=json.loads(p.read_text()) if p.exists() else {'phase':'not_started'}
 out['assets']=[json.loads(p.read_text()) for p in sorted((r/'setup').glob(f'asset-{name}-*.json'))]
 print(json.dumps(out,ensure_ascii=False,indent=2))
