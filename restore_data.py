"""Verify and reconstruct content-addressed MemRSI experimental artifacts (stdlib only)."""
import argparse,gzip,hashlib,json,tarfile
from pathlib import Path,PurePosixPath

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--text-only',action='store_true');a=p.parse_args()
 checks=json.loads((a.data_dir/'DATA-SHA256.json').read_text());need={'file-index.jsonl.gz','text-objects.tar.gz'}
 if not a.text_only:need.add('media-objects.tar.gz')
 for n in need:
  assert digest(a.data_dir/n)==checks[n]['sha256'],f'Archive checksum mismatch: {n}'
 with gzip.open(a.data_dir/'file-index.jsonl.gz','rt') as f:rows=[json.loads(l) for l in f]
 by_archive={}
 for r in rows:
  if a.text_only and r['disposition']!='text':continue
  by_archive.setdefault(r['archive'],{}).setdefault(r['object'],[]).append(r)
 a.output.mkdir(parents=True,exist_ok=True);base=a.output.resolve();count=0
 for n,objects in by_archive.items():
  with tarfile.open(a.data_dir/n,'r|gz') as archive:
   for member in archive:
    if member.name not in objects:continue
    assert member.isfile(),'Unexpected non-file archive object'
    data=archive.extractfile(member).read();sha=hashlib.sha256(data).hexdigest()
    for r in objects.pop(member.name):
     assert sha==r['public_sha256'] and len(data)==r['public_bytes'],r['path']
     rel=PurePosixPath(r['path']);assert not rel.is_absolute() and '..' not in rel.parts
     dest=base/str(rel);assert dest.resolve().is_relative_to(base),'Path escapes destination'
     dest.parent.mkdir(parents=True,exist_ok=True)
     if dest.exists():assert not dest.is_symlink() and digest(dest)==sha,f'Refusing overwrite: {dest}'
     else:dest.write_bytes(data)
     count+=1
  assert not objects,f'Missing objects: {len(objects)}'
 print(f'Verified and restored {count} files to {base}')
if __name__=='__main__':main()
