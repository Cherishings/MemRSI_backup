import json,pathlib,hashlib,collections,ast
B=pathlib.Path('/data/songziying/paos-libero-20261023')
N=['study-rsi-joint-v1','study-rsi-contract-v1','study-rsi-training-feedback-v2','study-rsi-typed-process-v1','study-rsi-transition-v1']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dig(v):return hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()
def read(p):return json.loads(p.read_text())
out={'scope':'read-only training-only; zero model calls','studies':{},'first_request_comparisons':[]};first={}
for n in N:
 r=B/n;rows=read(r/'learning/training/rows.json');assert len(rows)==32
 code={}
 for folder in ['source','code']:
  for p in sorted((r/folder).rglob('*.py')):
   if '__pycache__' not in str(p):code[str(p.relative_to(r))]=sha(p)
 funcs={}
 tree=ast.parse((r/'code/learn.py').read_text())
 for x in tree.body:
  if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name in ['install_runtime','replay_child','score_pair','run_stage']:funcs[x.name]=dig(ast.dump(x,include_attributes=False))
 parents=[]
 for row in rows:
  if row['arm']!='parent':continue
  p=pathlib.Path(row['output']);assert p.is_relative_to(r/'learning/training/replays')
  trace=p/'model-trace.jsonl';line=next((json.loads(x) for x in trace.open() if x.strip()),None)
  req=line['request'];resp=line['response'];key=(row['source_id'],row['repeat']);first[n,key]=line
  parents.append({'source_id':key[0],'repeat':key[1],'correct':row['correct'],'status':row['status'],'error_code':row.get('error_code'),'calls':row['logical_calls'],'policy':row['policy_sha256'],'fixture':read(p/'fixture-audit.json'),'first_request_sha256':dig(req),'first_response_sha256':dig(resp),'request_params':{k:v for k,v in req.items() if k not in ['messages','tools']},'response_keys':list(resp),'trace_sha256':sha(trace),'budget_sha256':sha(p/'resource-budget.json')})
 costs={a:{'calls':sum(x['logical_calls'] for x in rows if x['arm']==a),'incomplete':sum(x.get('model_cost_complete') is not True for x in rows if x['arm']==a),'unknown_requests':sum(x.get('model_cost_unknown_requests',0) or 0 for x in rows if x['arm']==a),'errors':dict(collections.Counter(x.get('error_code') or x['status'] for x in rows if x['arm']==a))} for a in ['parent','g_only_edit','u_only_edit','joint']}
 out['studies'][n]={'parent_file_sha256':sha(r/'parent-policy.json'),'budget_sha256':sha(r/'budget.json'),'manifest_sha256':sha(r/'training-sources.json'),'functions':funcs,'code':code,'parents':parents,'costs':costs,'rows_sha256':sha(r/'learning/training/rows.json')}
for key in sorted({k for n,k in first}):
 records=[(n,first[n,key]) for n in N]
 ref=records[0][1]['request']
 out['first_request_comparisons'].append({'source_repeat':key,'request_variants':len({dig(v['request']) for n,v in records}),'response_variants':len({dig(v['response']) for n,v in records}),'changed_request_fields':{n:[k for k in set(ref)|set(v['request']) if ref.get(k)!=v['request'].get(k)] for n,v in records}})
base=out['studies'][N[0]]['code'];out['changed_code_files']={n:[p for p in set(base)|set(out['studies'][n]['code']) if base.get(p)!=out['studies'][n]['code'].get(p)] for n in N}
print(json.dumps(out,ensure_ascii=False,indent=2))
