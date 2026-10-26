"""Persistent local public-CDN resolver/supervisor; signed URLs never enter logs."""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request

BASE = Path(__file__).resolve().parents[2] / 'outputs/official-memory-rmbench-20261017'
REMOTE = '/data/stormlab/xi/robot/official-memory-rmbench-20261017'


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    os.replace(temporary, path)


def remote(script, data):
    result = subprocess.run(['ssh', 'xi', 'python3', '-c', shlex.quote(script)],
                            input=json.dumps(data), text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('remote supervisor call failed')
    return json.loads(result.stdout)


UPDATE = '''import json,sys,os,subprocess
from pathlib import Path
p=json.load(sys.stdin);code=Path(p['code']);os.umask(0o077)
if p.get('urls'):
 tmp=code/'public-cdn-urls.tmp';tmp.write_text(json.dumps(p['urls']));os.replace(tmp,code/'public-cdn-urls.json')
ready=code/'assets-ready.json'
if ready.exists(): print(ready.read_text());raise SystemExit
folder=code/'asset-download';folder.mkdir(exist_ok=True);identity=folder/'identity.json';alive=False
if identity.exists():
 old=json.loads(identity.read_text());stat=Path('/proc')/str(old['pid'])/'stat'
 if stat.exists():
  fields=stat.read_text().rsplit(')',1)[1].split();alive=fields[0]!='Z' and fields[19]==old['start_ticks']
if not alive:
 with (folder/'download.log').open('a') as log:
  child=subprocess.Popen(['/data/stormlab/xi/robot/envs/rmbench-executor-20261017/bin/robot',str(code/'remote_download.py')],stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
  old={'pid':child.pid,'start_ticks':Path('/proc/%d/stat'%child.pid).read_text().rsplit(')',1)[1].split()[19]}
rows=[]
for path in folder.glob('*.json'):
 if path.name not in ['identity.json','failure.json']:rows.append(json.loads(path.read_text()))
print(json.dumps({'status':'downloading','identity':old,'files':rows}))
'''


def main():
    ctypes.CDLL(None).prctl(15, b'robot', 0, 0, 0)
    with (BASE / 'prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic(BASE / 'prepare-identity.json', {'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19], 'started': time.time()})
        manifest = json.loads((BASE / 'download-manifest.json').read_text())
        refreshed = 0
        while True:
            try:
                urls = {}
                if time.time() - refreshed > 600:
                    for item in manifest['files']:
                        if item['size'] > 100000000:
                            with urllib.request.urlopen(urllib.request.Request(item['url'], method='HEAD'), timeout=60) as response:
                                urls[item['local_path']] = response.geturl()
                        else:
                            urls[item['local_path']] = item['url']
                    refreshed = time.time()
                status = remote(UPDATE, {'code': REMOTE, 'urls': urls})
                status.update(updated=time.time(), scope='public assets preparation; no training or evaluation result')
                atomic(BASE / 'prepare-status.json', status)
                if status['status'] == 'ready':
                    atomic(BASE / 'assets-ready.json', status)
                    return
            except Exception as error:
                atomic(BASE / 'prepare-status.json', {'status': 'transport_retry', 'error_type': type(error).__name__, 'updated': time.time()})
            time.sleep(30)


if __name__ == '__main__':
    main()
