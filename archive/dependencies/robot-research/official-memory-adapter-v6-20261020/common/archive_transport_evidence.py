import json
from pathlib import Path
def read(p):return json.loads(Path(p).read_text())
def transport_evidence(attempt,result):
    if result.get('error_code')!='native_session_archival_failed':return None
    audits=sorted(Path(attempt).glob('rollover-*/audit.json'),key=lambda p:int(p.parent.name.split('-')[-1]))
    if not audits:return None
    a=read(audits[-1])
    if a.get('success') is not False:return None
    ep=Path(attempt)/'model-errors.jsonl'
    if not ep.exists():return None
    matches=[json.loads(x) for x in ep.read_text().splitlines() if json.loads(x).get('call')==a.get('model_calls')]
    if not matches:return None
    e=matches[-1]
    if e.get('http_status') not in (429,502,503,504):return None
    return {k:e.get(k) for k in ['http_status','code','stage','output_started','retryable','call']}
