exec(open('/tmp/paos-comparability-audit.py').read().split('for key in sorted')[0])
import re
pat=r'\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\]'
items=[]
for key in sorted({k for n,k in first}):
 reqs=[];stamps={}
 for n in N:
  v=json.loads(json.dumps(first[n,key]['request']));s=json.dumps(v,sort_keys=True);stamps[n]=sorted(set(re.findall(pat,s)));reqs.append(dig(re.sub(pat,'[REPLAY_TIME]',s)))
 items.append({'source_repeat':key,'normalized_request_variants':len(set(reqs)),'timestamps':stamps})
s=out['studies'][N[-1]]
print(json.dumps({'normalized_comparisons':items,'parameters':s['parents'][0]['request_params'],'response_keys':s['parents'][0]['response_keys'],'current_costs':s['costs']},indent=2))
