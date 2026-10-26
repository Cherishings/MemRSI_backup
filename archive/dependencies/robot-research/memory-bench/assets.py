"""Fetch official benchmark-specific assets; no writes to existing simulator assets."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile
import shutil
import fcntl
from prepare import ROOT, OUT, record

BOX_SIZES={'textures':538397915,'fixtures':472441720,'objaverse':2115607481,
           'aigen_objs':5799370473,'generative_textures':593204309}
RANGE_POOL=concurrent.futures.ThreadPoolExecutor(16)

def segmented(name,url,dest):
    """Bounded parallel HTTP ranges; preserve all verified chunks on reconnect."""
    total=BOX_SIZES[name];chunk_size=32*1024*1024
    chunks=dest.with_suffix('.chunks');chunks.mkdir(exist_ok=True)
    old=dest.with_name(dest.name+'.part')
    def one(start):
        end=min(total,start+chunk_size)-1;size=end-start+1
        chunk=chunks/str(start)
        if chunk.exists() and chunk.stat().st_size==size:return chunk
        if old.exists() and old.stat().st_size>=end+1:
            with old.open('rb') as source,chunk.open('wb') as target:
                source.seek(start);target.write(source.read(size))
            return chunk
        relay=os.environ.get('BENCH_ASSET_RELAY')
        target_url=relay+'/remem/'+name if relay else url
        part=chunk.with_suffix('.part');header=chunk.with_suffix('.headers')
        with (OUT/('range-'+name+'.log')).open('a') as log:
            subprocess.run(['curl','--fail','--location','--retry','4','--retry-delay','3',
                '--connect-timeout','20','--max-time','900','--range',f'{start}-{end}',
                '--dump-header',str(header),'--output',str(part),target_url],
                stdout=log,stderr=log,check=True)
        expected=f'content-range: bytes {start}-{end}/{total}'
        if part.stat().st_size!=size or expected not in header.read_text().lower():
            raise ValueError('range_validation_failed_'+name)
        part.replace(chunk);return chunk
    futures=[RANGE_POOL.submit(one,start) for start in range(0,total,chunk_size)]
    parts=[f.result() for f in futures]
    merged=dest.with_suffix('.joining')
    with merged.open('wb') as out:
        for p in parts:
            with p.open('rb') as source:shutil.copyfileobj(source,out,1024*1024)
    if merged.stat().st_size!=total:raise ValueError('merged_size_mismatch')
    merged.replace(dest)

def download(url, dest, expected=None):
    dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
    if expected and dest.exists() and dest.stat().st_size==expected:return
    part=dest.with_name(dest.name+'.part')
    relay=os.environ.get('BENCH_ASSET_RELAY')
    if relay:
        if '/RMBench/resolve/main/' in url:url=relay+'/rm/'+url.split('/RMBench/resolve/main/')[1]
        elif 'utexas.box.com/' in url:url=relay+'/remem/'+dest.stem.removeprefix('remem-')
    cmd=['curl','--fail','--location','--retry','4','--retry-delay','3',
         '--connect-timeout','20','--max-time','900','--continue-at','-',
         '--output',str(part),url]
    with (OUT/'assets-download.log').open('a') as f:
        subprocess.run(cmd,stdout=f,stderr=f,check=True)
    if expected and part.stat().st_size!=expected:raise ValueError('size_mismatch')
    part.replace(dest)

def rmbench():
    repo=ROOT/'src/RMBench';rows=[]
    for name in ['embodiments','objects']:
        rows+=json.loads((OUT/('rm-'+name+'.json')).read_text())
    files=[r for r in rows if r['type']=='file']
    record('rmbench-assets',phase='downloading',files=len(files))
    def one(r):
        path=r['path'];dest=repo/'assets'/path
        download('https://huggingface.co/datasets/TianxingChen/RMBench/resolve/main/'+path,
                 dest,r['size'])
        sha=r.get('lfs',{}).get('oid')
        if sha and hashlib.sha256(dest.read_bytes()).hexdigest()!=sha:
            raise ValueError('sha256_mismatch_'+path)
    with concurrent.futures.ThreadPoolExecutor(6) as pool:list(pool.map(one,files))
    for name,target in [('background_texture',ROOT/'src/RoboTwin/assets/background_texture')]:
        p=repo/'assets'/name
        if not p.exists():p.symlink_to(target,target_is_directory=True)
    p=repo/'envs/curobo'
    if not p.exists():p.symlink_to(ROOT/'src/RoboTwin/envs/curobo',target_is_directory=True)
    # The official setup operation expands asset-root placeholders only.
    subprocess.run(['python3','scripts/update_embodiment_config_path.py'],cwd=repo,check=True)
    record('rmbench-assets',phase='ready',files=len(files),official_repo='TianxingChen/RMBench')

def remembench():
    assets=ROOT/'src/ReMemBench/robocasa/models/assets'
    sources={
      'textures':('otdsyfjontk17jdp24bkhy2hgalofbh4',assets),
      'fixtures':('pobhbsjyacahg2mx8x4rm5fkz3wlmyzp',assets),
      'objaverse':('ejt1kc2v5vhae1rl4k5697i4xvpbjcox',assets/'objects'),
      'aigen_objs':('os3hrui06lasnuvwqpmwn0wcrduh6jg3',assets/'objects'),
      'generative_textures':('gf9nkadvfrowkb9lmkcx58jwt4d6c1g3',assets)}
    def one(item):
        name,(share,parent)=item; marker=OUT/('remem-asset-'+name+'.json')
        if marker.exists() and json.loads(marker.read_text()).get('phase')=='ready':return
        record('remem-asset-'+name,phase='downloading')
        archive=ROOT/'cache'/('remem-'+name+'.zip')
        if not archive.exists():segmented(name,'https://utexas.box.com/shared/static/'+share+'.zip',archive)
        parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                if not (parent/m.filename).resolve().is_relative_to(parent.resolve()):raise ValueError('unsafe_zip')
            z.extractall(parent)
        record('remem-asset-'+name,phase='ready',bytes=archive.stat().st_size)
    with concurrent.futures.ThreadPoolExecutor(3) as pool:list(pool.map(one,sources.items()))
    record('remembench-assets',phase='ready',source='official ReMemBench legacy assets, separate from RoboCasa365')

if __name__=='__main__':
    os.umask(0o077);OUT.mkdir(exist_ok=True)
    with (OUT/'assets.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            fs=[pool.submit(fn) for fn in [rmbench,remembench]]
            for f in fs:f.result()
