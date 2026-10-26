"""Read safe installation and native simulator checks, never model logs."""
import json
from pathlib import Path
from catalog import TASKS

ROOT=Path('/data/stormlab/xi/robot');BASE=ROOT/'memory-bench'

def status():
    out={}
    for bench,tasks in TASKS.items():
        row={'planned_tasks':len(tasks),'installation':{},'checks':{}}
        for stage in ('install','assets'):
            p=BASE/f'{bench}-{stage}.json'
            row['installation'][stage]=json.loads(p.read_text()) if p.exists() else {'phase':'missing'}
        for p in sorted((ROOT/'runs').glob(f'memory-{bench}-*/episode/result.json')):
            data=json.loads(p.read_text())
            if data.get('mode')=='smoke':
                row['checks'][data['task']]={k:data.get(k) for k in
                    ('status','steps','error_type','error','finished')}
        row['passed_tasks']=sum(v['status']=='passed' for v in row['checks'].values())
        row['all_tasks_smoke_passed']=row['passed_tasks']==len(tasks)
        out[bench]=row
    out['meaning']='Smoke checks verify camera, simulator and action interface only; not PAOS/MemRSI task success.'
    return out

if __name__=='__main__':print(json.dumps(status(),indent=2))
