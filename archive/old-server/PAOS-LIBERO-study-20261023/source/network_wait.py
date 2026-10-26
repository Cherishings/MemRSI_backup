"""Operational outage handling; never injects task hints or changes model output."""
import json,time,urllib.request
from pathlib import Path
HEALTH_URL='http://127.0.0.1:19099/connectivity'
BACKOFF=(10,20,30,60)
TRANSPORT_TYPES={'APIConnectionError','APITimeoutError','ConnectError','ReadTimeout','ConnectTimeout'}
UPSTREAM_TYPES={'ReadTimeout','ConnectTimeout','ConnectionError','ChunkedEncodingError','SSLError','ProxyError'}

def transient(error):
    if error.get('code') or error.get('http_status') in (400,401,403,404,422,429):return False
    if error.get('http_status') is None:return error.get('exception_type') in TRANSPORT_TYPES
    return (error.get('http_status') in (408,500,502,503,504)
        and error.get('stage') in ('http_connect','http_response','stream')
        and error.get('upstream_error_type') in UPSTREAM_TYPES)

def probe():
    try:
        with urllib.request.urlopen(HEALTH_URL,timeout=15) as f:data=json.load(f)
        return data.get('transport_ready') is True
    except (OSError,ValueError):return False

class WaitClock:
    def __init__(self,output):
        self.path=Path(output)/'transport-wait.json';self.total=0.;self.start=None
    def write(self,reason,request_hash=None):
        data=dict(waiting=self.start is not None,waiting_since_monotonic=self.start,
            accumulated_wait_seconds=self.total,reason=reason,request_sha256=request_hash,updated_unix=time.time())
        p=self.path.with_suffix('.tmp');p.write_text(json.dumps(data));p.replace(self.path)
    def begin(self,reason,request_hash=None,since=None):
        if self.start is None:self.start=time.monotonic() if since is None else since
        self.write(reason,request_hash)
    def end(self):
        if self.start is not None:self.total+=time.monotonic()-self.start;self.start=None
        self.write('connected')

def paused_seconds(output,now=None):
    try:data=json.loads((Path(output)/'transport-wait.json').read_text())
    except (OSError,ValueError):return 0.
    total=max(0.,float(data.get('accumulated_wait_seconds',0)))
    if data.get('waiting') and isinstance(data.get('waiting_since_monotonic'),(int,float)):
        total+=max(0.,(time.monotonic() if now is None else now)-data['waiting_since_monotonic'])
    return total
