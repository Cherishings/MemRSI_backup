"""Collect fixed-parent RSI sources; no final-test jobs and no rule edits."""
import json,pathlib,shutil,hashlib,sys,os,time,subprocess
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study-scope-v4';r=b/'study-rsi-v4-sources'
assert not r.exists()
assert json.loads((b/'active-study.json').read_text())['root']==str(old)
q=json.loads((old/'queue-status.json').read_text());assert q['phase']=='development_complete'
assert not pathlib.Path('/proc/'+str(q['pid'])).exists()
m=json.loads((old/'registration.json').read_text());a=json.loads((old/'allocation.json').read_text());node=str(a['node']);init={'107':0,'108':1}[node]
prior=json.loads((old/'development-schedule.json').read_text())
assert len(prior)==5
for j in prior:assert (pathlib.Path(j['output'])/'result.json').exists()
existing=next(j for j in prior if j['arm']=='gu_parent')
training=[c for c in m['training_conditions'] if c['init']==init and c['condition_id']!=existing['condition_id']]
validation=[c for c in m['validation_conditions'] if c['init']==init]
assert len(training)==3 and len(validation)==2
assert {c['condition_id'] for c in training}<=set(a['allowed_condition_ids'])
assert not {c['condition_id'] for c in training+validation}&{c['condition_id'] for c in m['test_conditions']}
r.mkdir()
for name in ('code','source','policies'):shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to(old/'paos-core',target_is_directory=True)
for name in ('orders.json','budget.json','parent-policy.json','env.sh'):shutil.copy2(old/name,r/name)
for p in list((r/'code').rglob('*.py'))+list((r/'source').glob('*.py'))+[r/'env.sh']:
 p.write_text(p.read_text().replace(str(old),str(r)))
# Close the preflight-only socket; inference has its own reliable client.
p=r/'code/queue_v2.py';s=p.read_text();needle='metadata=client.get_server_metadata();break'
assert needle in s
s=s.replace(needle,'metadata=client.get_server_metadata();client._ws.close();break');p.write_text(s)
a.update(phase='RSI source collection',role='fixed parent source shard',allowed_condition_ids=[c['condition_id'] for c in training+validation],final_test_allowed=False)
(r/'allocation.json').write_text(json.dumps(a,indent=2)+'\n')
schedule=[dict(c,arm='gu_parent',output=str(r/'development'/c['condition_id']/'gu_parent')) for c in training+validation]
(r/'development-schedule.json').write_text(json.dumps(schedule,indent=2)+'\n')
for name in ('jobs','logs'):(r/name).mkdir()
(r/'training-sources.json').write_text(json.dumps([{'id':existing['condition_id'],'output':existing['output']}]+[{'id':j['condition_id'],'output':j['output']} for j in schedule[:3]],indent=2)+'\n')
(r/'validation-sources.json').write_text(json.dumps([{'id':j['condition_id'],'output':j['output']} for j in schedule[3:]],indent=2)+'\n')
record={'kind':'fixed_parent_RSI_source_collection','registered_at':time.time(),'node':node,
 'parent_file_sha256':hashlib.sha256((r/'parent-policy.json').read_bytes()).hexdigest(),
 'training_conditions':[c['condition_id'] for c in training],
 'reserved_validation_conditions':[c['condition_id'] for c in validation],
 'existing_training_source':existing['output'],'new_jobs':5,
 'manual_rule_changes':False,'test_jobs':0,'separate_source_shards':True,
 'validation_content_not_for_manual_rule_edits':True,
 'next_gate':'Aggregate both source manifests; one model G proposal and one U proposal from training only, freeze candidates before validation selection; no automatic final test launch',
 'infrastructure_change':'close idle preflight socket; independent inference client unchanged',
 'preserve_all_failures_costs_and_unreconstructible_sources':True}
(r/'source-registration.json').write_text(json.dumps(record,indent=2)+'\n')
m['registered_at']=time.time();m['administrative_amendments'].append(record)
for name in ('manual-revision.json','baseline-paired-results.json'):m['frozen_files'].pop(name,None)
for name in m['frozen_files']:m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
for name in ('source-registration.json','training-sources.json','validation-sources.json'):
 m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n');(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
assert (r/'parent-policy.json').read_bytes()==(old/'parent-policy.json').read_bytes()
assert (r/'budget.json').read_bytes()==(old/'budget.json').read_bytes()
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
os.environ['PYTHONPATH']=os.environ.get('PYTHONPATH','').replace(str(old),str(r))
import runtime_adapter
runtime_adapter.configure(7,20517,str(r/'paos-core'))
# Check the installed preflight client's connection attribute without any model call.
from openpi_client.websocket_client_policy import WebsocketClientPolicy
client=WebsocketClientPolicy('127.0.0.1',20517)
assert client.get_server_metadata().get('paired_sampling') is True
client._ws.close()
with (r/'queue.log').open('x') as log:
 p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=os.environ.copy())
(r/'queue-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}))
t=b/'active-study.tmp';t.write_text(json.dumps({'root':str(r),'time':time.time()}));t.replace(b/'active-study.json')
print(json.dumps({'node':node,'root':str(r),'queue_pid':p.pid,'jobs':5,'first':schedule[0]}))
