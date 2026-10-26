"""Bounded training evidence view; omissions explicit, source archive retained."""
import json,hashlib

def render(data, cap=1200):
 if type(cap) is not int or cap<100:raise ValueError('invalid_cap')
 if data.get('validation_read') is not False or data.get('test_read') is not False:raise ValueError('scope')
 blobs=data['blobs']
 def text(h):
  s=blobs[h]
  if hashlib.sha256(s.encode()).hexdigest()!=h:raise ValueError('blob_hash')
  return s
 def excerpt(h):
  s=text(h); n=len(s)
  # Symmetric head/tail, no score-dependent excerpts.
  if n<=cap:return {'text':s,'chars':n,'omitted':0,'sha256':h}
  left=cap//2;right=cap-left
  return {'text':s[:left]+'\n[OMITTED MIDDLE]\n'+s[-right:],'chars':n,'omitted':n-cap,'sha256':h}
 rows=[]
 for row in sorted(data['rows'],key=lambda r:tuple(map(str,r['key']))):
  ts=sorted(row['transitions'],key=lambda t:int(t['archive'].split('-')[-1]))
  if len({t['archive'] for t in ts})!=len(ts):raise ValueError('duplicate_archive')
  inventory=[]
  for t in ts:
   for h in t['refs'].values():text(h)
   inventory.append([t['archive'],t['last_received_event'],t['success']])
  # Each arm gets its last saved transition, independent of status and score.
  selected=ts[-1:]
  details=[{'archive':t['archive'],'event':t['last_received_event'],'fields':{n:excerpt(t['refs'][n]) for n in ['memory-before.md','memory-after.md','messages-before.json']}} for t in selected]
  rows.append({'key':row['key'],'status':row['status'],'correct':row.get('correct'),'planned':row.get('planned'),'inventory':inventory,'details':details,'omitted_transition_details':len(ts)-len(selected)})
 return {'scope':'training-only','selection':'last saved archive per registered row, independent of outcome; not necessarily matched event across arms','warning':'Tool archive success is not semantic correctness. Omitted text cannot establish absence. Complete source archive is retained but is not wholly presented here.','cap_per_field':cap,'rows':rows,'coverage':{'rows':len(rows),'inventory_transitions':sum(len(r['inventory']) for r in rows),'detailed_transitions':sum(len(r['details']) for r in rows),'omitted_chars_in_selected_fields':sum(f['omitted'] for r in rows for t in r['details'] for f in t['fields'].values())}}
if __name__=='__main__':
 import sys
 print(json.dumps(render(json.load(open(sys.argv[1]))),ensure_ascii=False,separators=(',',':')))
