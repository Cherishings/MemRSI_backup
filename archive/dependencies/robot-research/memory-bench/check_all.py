"""Single bounded setup sweep of official tasks; no learned-policy evaluation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from catalog import TASKS

BASE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('benchmark',choices=TASKS)
    p.add_argument('--gpu',type=int,choices=[0,1,2],required=True)
    p.add_argument('--wait-assets',action='store_true')
    a=p.parse_args();marker=BASE/f'{a.benchmark}-assets.json'
    deadline=time.monotonic()+6*3600
    while not marker.exists() or json.loads(marker.read_text()).get('phase')!='ready':
        if not a.wait_assets or time.monotonic()>=deadline:return 3
        time.sleep(15)
    codes=[]
    for task in TASKS[a.benchmark]:
        code=subprocess.call([sys.executable,str(BASE/'run.py'),a.benchmark,
            '--task',task,'--gpu',str(a.gpu),'--shared-smoke','--wait'])
        codes.append({'task':task,'exit_code':code})
        if code:break  # diagnose a real setup fault before spending on the rest
    (BASE/f'{a.benchmark}-sweep.json').write_text(json.dumps(codes,indent=2))
    return max(x['exit_code'] for x in codes)

if __name__=='__main__':raise SystemExit(main())
