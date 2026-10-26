"""Fixed last-common-event training view, plus explicitly attributed diagnostic."""
import json,hashlib
from collections import defaultdict
ARMS={'parent','g_only_edit','u_only_edit','joint'}
def build_view(data):
 if data.get('validation_read') is not False or data.get('test_read') is not False:raise ValueError('scope')
 blobs=data['blobs']; groups=defaultdict(dict); texts={}
 def add(h):
  s=blobs[h]
  if hashlib.sha256(s.encode()).hexdigest()!=h:raise ValueError('hash')
  texts[h]=s;return h
 def messages(h):
  raw=blobs[h]
  if hashlib.sha256(raw.encode()).hexdigest()!=h:raise ValueError('hash')
  items=json.loads(raw); omissions=[]
  for i,m in enumerate(items):
   content=m.get('content')
   if m.get('role')!='user' or not isinstance(content,str):continue
   marker='Current scene observations: '
   if marker in content:
    prefix,tail=content.split(marker,1)
    try: value,end=json.JSONDecoder().raw_decode(tail)
    except ValueError:continue
    if isinstance(value,dict):
     m['content']=prefix+marker+'[GEOMETRY OMITTED]'+tail[end:];omissions.append({'message':i,'kind':'current_scene_observations','chars':end})
   elif 'Execution feedback: ' in content:
    prefix,tail=content.split('Execution feedback: ',1)
    value,end=json.JSONDecoder().raw_decode(tail)
    if 'scene_observation' in value:
     removed=value.pop('scene_observation');omissions.append({'message':i,'kind':'receipt_scene_observation','chars':len(json.dumps(removed,ensure_ascii=False))})
     m['content']=prefix+'Execution feedback: '+json.dumps(value,ensure_ascii=False)+tail[end:]
  return {'source_sha256':h,'messages':items,'omissions':omissions}
 def detail(row,t):
  return {'key':row['key'],'archive':t['archive'],'event':t['last_received_event'],'refs':{n:add(t['refs'][n]) for n in ['memory-before.md','memory-after.md']},'public_messages':messages(t['refs']['messages-before.json'])}
 for row in data['rows']:
  source,arm,repeat,policy=row['key'];k=(source,repeat)
  if arm in groups[k]:raise ValueError('duplicate_arm')
  groups[k][arm]=row
 selected=[];summaries=[]
 for k,arms in sorted(groups.items()):
  if set(arms)!=ARMS:raise ValueError('incomplete_pair')
  indices={}
  for arm,row in arms.items():
   ix={}
   for t in row['transitions']:
    event=t['last_received_event']
    if type(event) is not int or event in ix:raise ValueError('ambiguous_event')
    ix[event]=t
   indices[arm]=ix
   summaries.append({'key':row['key'],'status':row['status'],'correct':row.get('correct'),'planned':row.get('planned'),'saved_events':sorted(ix)})
  common=set.intersection(*(set(ix) for ix in indices.values()))
  event=max(common) if common else None
  selected.append({'source_repeat':k,'shared_event':event,'details':[detail(arms[a],indices[a][event]) for a in sorted(ARMS)] if common else [],'missing_shared_event':not bool(common)})
 # This previously audited case is explicitly diagnostic, not score-neutral sampling.
 diagnostic=[]
 for row in data['rows']:
  if row['key'][1]=='joint' and row['key'][2]==1:
   for t in row['transitions']:
    if t['refs']['memory-after.md']=='e4259eff3a477909e77167ea5d3a2b5392aac57f0a5d50881ff07dc83142cc6e':
     diagnostic.append(detail(row,t))
 return {'scope':'training-only','selection':'latest shared saved event per source/repeat across all four arms; no outcome filter','limitations':'Shared event is alignment, not identical model history or causal identification. Other transitions are inventoried only, not fully provided. Source-error-corrected is not full task success.','summaries':sorted(summaries,key=lambda r:tuple(map(str,r['key']))),'paired':selected,'diagnostic':{'selection':'previously identified erroneous memory transition, explicitly selected for diagnosis','details':diagnostic},'shared_text':texts,'memory_text_truncated':False,'message_geometry_omitted':True}
if __name__=='__main__':
 import sys
 print(json.dumps(build_view(json.load(open(sys.argv[1]))),ensure_ascii=False,separators=(',',':')))

def pack_memories(view):
 """Exact prefix/suffix delta references; no semantic summarization."""
 import copy
 out=copy.deepcopy(view);pool=[];ids={}
 for h,s in sorted(view['shared_text'].items()):
  best={'text':s};cost=len(json.dumps(best,ensure_ascii=False))
  for i,previous in enumerate(pool):
   base=unpack_one(pool,i);a=0
   while a<min(len(base),len(s)) and base[a]==s[a]:a+=1
   b=0
   while b<min(len(base)-a,len(s)-a) and base[len(base)-1-b]==s[len(s)-1-b]:b+=1
   candidate={'base':i,'prefix':a,'suffix':b,'middle':s[a:len(s)-b if b else len(s)]}
   size=len(json.dumps(candidate,ensure_ascii=False))
   if size<cost:best=candidate;cost=size
  ids[h]=len(pool);pool.append(best)
 for group in out['paired']+[out['diagnostic']]:
  for detail in group['details']:
   detail['refs']={n:ids[h] for n,h in detail['refs'].items()}
 out.pop('shared_text');out['memory_pool']=pool
 out['encoding']='memory_pool entries are full text or base prefix + middle + base suffix; suffix=0 contributes empty text; exact reconstruction, not summarization'
 return out

def unpack_one(pool,i):
 x=pool[i]
 if 'text' in x:return x['text']
 if not 0<=x['base']<i:raise ValueError('invalid_reference')
 s=unpack_one(pool,x['base']);return s[:x['prefix']]+x['middle']+(s[-x['suffix']:] if x['suffix'] else '')
