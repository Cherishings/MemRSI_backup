import hashlib,json,shutil,time,sys
from pathlib import Path
old=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023-gpu67')
r=old.with_name(old.name+'-learn48k-runtimefix')
assert not r.exists()
m=json.loads((old/'registration.json').read_text())
for name,h in m['frozen_files'].items():assert hashlib.sha256((old/name).read_bytes()).hexdigest()==h,name
r.mkdir()
for name in ('code','source','paos-core'):shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
for name in ('orders.json','budget.json','parent-policy.json'):shutil.copy2(old/name,r/name)
(r/'development').symlink_to(old/'development',target_is_directory=True)
for name in ('learn.py','test_learn.py','method.py'):shutil.copy2(Path(__file__).parent/name,r/'code'/name)
m['registered_at']=time.time()
m['administrative_amendments'].append({'time':time.time(),'reason':'User authorizes increased development learning budget and continuation','previous_root':str(old),'previous_registration_sha256':(old/'registration.sha256').read_text().strip(),'optimizer_input_tokens':49152,'optimizer_output_tokens':8192,'operator_character_limit':4096,'learning_call_limit':24000,'old_learning_wire_calls':0,'existing_development_preserved':True,'actor_budget_and_scoring_unchanged':True,'final_test_not_started':True})
for file,old_cap,new_cap in [('memory_policy.py','> 1800','> 32768'),('memory_design.py','>1600','>4096')]:
 p=r/'source'/file;p.write_text(p.read_text().replace(old_cap,new_cap))
for name in m['frozen_files']:m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
(r/'registration.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
(r/'runtime-control').mkdir()
# Preserve the already generated proposals without resampling. Only capacity guard changes.
prior=old.with_name(old.name+'-learn48k-rules4k')/'learning'
(r/'learning').mkdir()
shutil.copytree(prior/'proposals',r/'learning/proposals')
shutil.copytree(prior/'critics',r/'learning/critics')
shutil.copy2(prior/'learning-call-ledger.json',r/'learning/learning-call-ledger.json')

previous=old.with_name(old.name+'-learn48k-ready')/'learning'
shutil.copy2(previous/'learning-call-ledger.json',r/'learning/learning-call-ledger.json')
valid=previous/'training/replays/000-parent-r0'
assert json.loads((valid/'result.json').read_text())['status']=='source_error_corrected'
shutil.copytree(valid,r/'learning/training/replays/000-parent-r0')
policies={p.stem:json.loads(p.read_text()) for p in (previous/'policies').glob('*.json')}
(r/'preflight-policies.json').write_text(json.dumps(policies))
shutil.copy2(Path(__file__).parent/'preflight.py',r/'runtime-control/preflight.py')
import subprocess,os
subprocess.run([sys.executable,str(r/'runtime-control/preflight.py'),str(r)],check=True,env=dict(os.environ,LITELLM_LOCAL_MODEL_COST_MAP='True'))
print(r)
