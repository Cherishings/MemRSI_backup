"""Reconstruct exact runtime legacy assets using official ZIP CRCs and HTTP ranges.

Only macOS sidecar files are omitted. Different model.xml files come from the old
official ZIP, not from the new RoboCasa environment. Existing environments untouched.
"""
import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import struct
import time
import urllib.request
import zipfile
import zlib
from prepare import ROOT,OUT,record
from assets import BOX_SIZES

def required(r):
    return not r['directory'] and not any(x.startswith('.') or x=='__MACOSX'
        for x in Path(r['name']).parts)

def fetch_range(name,start,end):
    # Reuse earlier exact range downloads, even if the complete ZIP was not finished.
    chunk_size=32*1024*1024;chunk_start=start//chunk_size*chunk_size
    p=ROOT/'cache'/f'remem-{name}.chunks'/str(chunk_start)
    if end//chunk_size==start//chunk_size and p.exists() and p.stat().st_size>end-chunk_start:
        with p.open('rb') as f:f.seek(start-chunk_start);return f.read(end-start+1)
    url=os.environ['BENCH_ASSET_RELAY']+'/remem/'+name
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(req,timeout=60) as response:
                if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{BOX_SIZES[name]}':
                    raise ValueError('range_not_honored')
                data=response.read()
            if len(data)!=end-start+1:raise ValueError('short_range')
            return data
        except Exception:
            if attempt==3:raise
            time.sleep(2*(attempt+1))

def original_member(name,r):
    start=r['offset']
    data=fetch_range(name,start,min(BOX_SIZES[name]-1,start+30+len(r['name'].encode())+1024+r['compressed']-1))
    if data[:4]!=b'PK\x03\x04':raise ValueError('zip_local_header')
    fn,extra=struct.unpack_from('<HH',data,26);begin=30+fn+extra;end=begin+r['compressed']
    if end>len(data):data=fetch_range(name,start,start+end-1)
    payload=data[begin:end]
    if r['compression']==8:payload=zlib.decompress(payload,-15)
    elif r['compression']!=0:raise ValueError('unsupported_zip_compression')
    if len(payload)!=r['size'] or zlib.crc32(payload)!=r['crc']:raise ValueError('legacy_member_crc')
    return payload

def install(name):
    rows=[r for r in json.loads((OUT/f'legacy-{name}.json').read_text()) if required(r)]
    new_archive=ROOT/'cache'/f'casa-{name}.zip'
    with zipfile.ZipFile(new_archive) as z:
        new={i.filename:(i.file_size,i.CRC) for i in z.infolist()}
    sub=Path('objects') if name!='generative_textures' else Path()
    parent=ROOT/'src/ReMemBench/robocasa/models/assets'/sub
    source=ROOT/'src/robocasa/robocasa/models/assets'/sub
    same=[r for r in rows if new.get(r['name'])==(r['size'],r['crc'])]
    different=[r for r in rows if new.get(r['name'])!=(r['size'],r['crc'])]
    record('remem-asset-'+name,phase='verified_reuse',runtime_files=len(rows),
           matching_files=len(same),legacy_specific_files=len(different))
    def write(r,data):
        p=parent/r['name']
        if not p.resolve().is_relative_to(parent.resolve()):raise ValueError('unsafe_path')
        p.parent.mkdir(parents=True,exist_ok=True)
        tmp=p.with_name(p.name+'.installing');tmp.write_bytes(data);tmp.replace(p)
    def already(r):
        p=parent/r['name']
        return p.exists() and p.stat().st_size==r['size'] and zlib.crc32(p.read_bytes())==r['crc']
    def reuse(r):
        if already(r):return
        data=(source/r['name']).read_bytes()
        if len(data)!=r['size'] or zlib.crc32(data)!=r['crc']:raise ValueError('installed_asset_crc')
        write(r,data)
    def retrieve(r):
        if not already(r):write(r,original_member(name,r))
    with concurrent.futures.ThreadPoolExecutor(8) as pool:list(pool.map(reuse,same))
    with concurrent.futures.ThreadPoolExecutor(24) as pool:list(pool.map(retrieve,different))
    record('remem-asset-'+name,phase='ready',runtime_files=len(rows),matching_files=len(same),
           legacy_specific_files=len(different),verification='official legacy ZIP CRC32 and size for every runtime file',
           excluded='macOS __MACOSX and dotfiles only')

if __name__=='__main__':
    os.umask(0o077)
    with (OUT/'assets.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            list(pool.map(install,['objaverse','aigen_objs','generative_textures']))
        for name in ['textures','fixtures','objaverse','aigen_objs','generative_textures']:
            assert json.loads((OUT/f'remem-asset-{name}.json').read_text())['phase']=='ready'
        record('remembench-assets',phase='ready',source='official legacy runtime assets; verified per-file reconstruction')
