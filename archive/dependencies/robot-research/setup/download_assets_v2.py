"""Download public official assets only; keep archives, validate archive paths."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

ROOT=Path('/data/stormlab/xi/robot')

def job(item):
    name,url,parent=item
    os.umask(0o077)
    status=ROOT/'setup'/f'asset-{name}.json';archive=ROOT/'cache'/f'{name}.zip'
    def update(**kw):
        tmp=status.with_suffix('.tmp');tmp.write_text(json.dumps(dict(name=name,updated=time.time(),**kw)));tmp.replace(status)
    if status.exists() and json.loads(status.read_text()).get('phase')=='complete':return
    update(phase='downloading',archive=str(archive))
    with (ROOT/'logs'/f'asset-{name}.log').open('a') as log:
        for attempt in range(12):
            p=subprocess.run(['curl','--fail','--location','--connect-timeout','30','--max-time','900','--speed-time','120','--speed-limit','1024','--continue-at','-','--output',str(archive),url],stdout=log,stderr=log)
            if p.returncode == 0: break
            time.sleep(min(20, 2*(attempt+1)))
    if p.returncode:
        update(phase='failed_download',code=p.returncode);return
    update(phase='extracting',archive=str(archive),bytes=archive.stat().st_size)
    parent=Path(parent);parent.mkdir(parents=True,exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if not (parent/member.filename).resolve().is_relative_to(parent.resolve()):raise ValueError('unsafe_zip_path')
            z.extractall(parent)
        update(phase='complete',archive=str(archive),bytes=archive.stat().st_size,destination=str(parent))
    except Exception as e:update(phase='failed_extract',error_type=type(e).__name__)

if __name__=='__main__':
    prior=ROOT/'setup/download-assets-recovery.json'
    if prior.exists():
        identity=json.loads(prior.read_text())
        while True:
            try:
                proc=Path(f"/proc/{identity['pid']}/stat").read_text().rsplit(')',1)[1].split()
                alive=proc[0]!='Z' and proc[19]==identity['start_ticks']
            except FileNotFoundError: alive=False
            if not alive: break
            time.sleep(10)
    jobs=[]
    for n in ('background_texture','embodiments','objects'):
        jobs.append(('twin-'+n,'https://huggingface.co/datasets/TianxingChen/RoboTwin2.0/resolve/main/'+n+'.zip',ROOT/'src/RoboTwin/assets'))
    assets=ROOT/'src/robocasa/robocasa/models/assets'
    links=json.loads((assets/'box_links/box_links_assets.json').read_text())
    for key,parent in [('textures',assets),('generative_textures',assets),('fixtures_lightwheel',assets),
        ('objaverse',assets/'objects'),('aigen_objs',assets/'objects'),('objects_lightwheel',assets/'objects')]:
        shared=links[key];url=shared.split('/s/')[0]+'/shared/static/'+shared.rstrip('/').split('/')[-1]+'.zip'
        jobs.append(('casa-'+key,url,parent))
    with concurrent.futures.ThreadPoolExecutor(3) as pool:list(pool.map(job,jobs))
