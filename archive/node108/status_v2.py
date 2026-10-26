import pathlib,json,time,os
r=pathlib.Path('/data/songziying/paos-libero-20261023/study-scope-v2');s=json.loads((r/'queue-status.json').read_text());p=pathlib.Path(s['job']['output']) if 'job' in s else None
record={'time':time.time(),'queue':s,'alive':pathlib.Path('/proc/'+str(s['pid'])).exists()}
if p:
 record['scenes_initialized']=len(list(p.glob('*/physical/initial.json')))
 for f in ('progress.json','calls.json','result.json'):
  q=p/f
  if q.exists():
   d=json.loads(q.read_text());record[f]={k:d[k] for k in ('status','phase','sessions_completed','correct_checkpoints','calls','wire_attempts','transport_retries','failure','error_code') if k in d}
print(json.dumps(record,indent=2))
