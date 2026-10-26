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
        p=subprocess.run(['curl','--fail','--location','--retry','3','--connect-timeout','30','--speed-time','120','--speed-limit','1024','--continue-at','-','--output',str(archive),url],stdout=log,stderr=log)
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
