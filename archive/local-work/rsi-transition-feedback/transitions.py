"""Lossless archive-transition evidence from a complete registered training run."""
from pathlib import Path
import hashlib,json

def build(root):
 root=Path(root).resolve(); folder=root/'learning'/'training'; base=folder/'replays'
 blobs={}; files={}
 def get(path):
  path=Path(path)
  if not path.resolve().is_relative_to(folder): raise ValueError('nontraining_path')
  raw=path.read_bytes(); h=hashlib.sha256(raw).hexdigest()
  files[str(path.relative_to(folder))]=h
  blobs[h]=raw.decode('utf-8')
  return h,blobs[h]
 def obj(path): return json.loads(get(path)[1])
 manifest=obj(folder/'manifest.json'); rows=obj(folder/'rows.json')
 def key(r): return tuple(r[k] for k in ('source_id','arm','repeat','policy_sha256'))
 schedule=manifest['schedule']; allowed={key(r) for r in schedule}
 if len(rows)!=32 or len(schedule)!=32 or len(allowed)!=32:raise ValueError('incomplete_or_duplicate_manifest')
 if {key(r) for r in rows}!=allowed or len({key(r) for r in rows})!=32:raise ValueError('unexpected_rows')
 output=[]; paths=set()
 for row in rows:
  p=Path(row['output']).resolve()
  if not p.is_relative_to(base) or p in paths:raise ValueError('nontraining_or_duplicate_output')
  paths.add(p)
  result=obj(p/'result.json')
  if result['policy_sha256']!=row['policy_sha256']:raise ValueError('policy_mismatch')
  transitions=[]
  for archive in sorted(p.glob('rollover-*'),key=lambda x:int(x.name.split('-')[-1])):
   refs={name:get(archive/name)[0] for name in ['memory-before.md','memory-after.md','messages-before.json','audit.json']}
   audit=json.loads(blobs[refs['audit.json']])
   if audit.get('memory_before_sha256') != refs['memory-before.md'] or audit.get('memory_after_sha256') != refs['memory-after.md']:raise ValueError('archive_hash_mismatch')
   if audit.get('policy_sha256') != row['policy_sha256']:raise ValueError('archive_policy_mismatch')
   transitions.append({'archive':archive.name,'refs':refs,'success':audit.get('success'),'last_received_event':audit.get('last_received_event')})
  output.append({'key':list(key(row)),'status':row['status'],'correct':row.get('correct'),'planned':row.get('planned'),'transitions':transitions})
 return {'scope':'all registered training rows and all saved archive transitions; no semantic success labels inferred','rows':output,'files':files,'blobs':blobs,'truncation':False,'validation_read':False,'test_read':False}
if __name__=='__main__':
 import sys
 print(json.dumps(build(sys.argv[1]),ensure_ascii=False))
