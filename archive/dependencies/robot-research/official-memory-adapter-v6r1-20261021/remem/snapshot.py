"""Safe remote structured snapshot. Does not inspect credentials/private logs."""
from pathlib import Path
import json
ROOT=Path('/data/stormlab/xi/robot/runs/official-online-remem-r4-20261017')
def read(path):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return None

def check(p):
    if not p:return None
    q=Path(f"/proc/{p['pid']}/stat")
    if not q.exists():return dict(**p,alive=False)
    fields=q.read_text().rsplit(')',1)[1].split()
    return dict(**p,alive=fields[19]==str(p['start_ticks']) and fields[0]!='Z',actual_start_ticks=fields[19],process_state=fields[0])

out={}
for rel in ['preflight-identity.json','preflight-progress.json','initial-state-check/result.json','segment-check/result.json','entry-smoke/identity.json','entry-smoke/progress.json','entry-smoke/rows.json','entry-evaluation-calls.json','paired/identity.json','paired/progress.json','paired/rows.json']:
    data=read(ROOT/rel)
    if isinstance(data,dict):
        if 'pid' in data:data=check(data)
        if 'child' in data:data['child']=check(data['child'])
        data.pop('source_hashes',None)
        if 'rows' in data:data['initializations_checked']=len(data.pop('rows'))
    out[rel]=data
print(json.dumps(out,indent=2))
