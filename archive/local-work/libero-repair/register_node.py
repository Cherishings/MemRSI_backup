from pathlib import Path
import hashlib,json,time,socket,sys,subprocess,os
b=Path('/data/songziying/paos-libero-20261023');r=b/'study'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
m=json.loads((r/'registration.json').read_text())
if not (r/'deployment-registration.json').exists():
 old=(r/'registration.sha256').read_text().strip()
 (r/'deployment-registration.json').write_text(json.dumps({'source_registration_sha256':old,'source_registration':m},indent=2))
 m['gpus']=[7];m['registered_at']=time.time()
 m['deployment_backend']={'policy':'pi05_libero PyTorch DCU','physics':'LIBERO native with software EGL','training_only':True,'do_not_pool_with_cuda_results':True,'model_conversion_manifest':json.loads((b/'migration/models/pi05_libero/conversion_manifest.json').read_text()),'policy_image':'phyagentos-openpi-hcu:pi05-v016-dtk2604-20260901'}
 m['administrative_amendments'].append({'time':time.time(),'reason':'User authorized deployment on new DCU hosts','root':str(r),'gpus':[7],'hardware_block':'DCU PyTorch, separate from CUDA JAX','old_results_reused':False})
 for name in m['frozen_files']:m['frozen_files'][name]=sha(r/name)
 (r/'registration.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
 (r/'registration.sha256').write_text(sha(r/'registration.json')+'\n')
allocation=json.loads((b/'allocation.json').read_text())
assert sys.argv[1] in allocation['allowed_condition_ids'], 'Condition assigned to another node; refusing duplicate work'
condition=next(x for x in m['training_conditions'] if x['condition_id']==sys.argv[1])
policy=r/'parent-policy.json';out=r/'development/train'/condition['condition_id']/'gu_parent'
assert not out.exists(),'Already started: existing outputs must be preserved'
with socket.create_connection(('127.0.0.1',20507),3):pass
job=dict(condition,arm='gu_parent',phase='development/train',gpu=7,policy=str(policy),policy_file_sha256=sha(policy),output=str(out))
jobfile=b/('development-job-'+condition['condition_id']+'.json');jobfile.write_text(json.dumps(job,indent=2))
with (b/'logs'/('development-'+condition['condition_id']+'.log')).open('x') as f:
 p=subprocess.Popen([str(b/'migration/conda-envs/paos-agent/bin/python'),str(r/'code/run_case.py'),'--root',str(r),'--job',str(jobfile)],stdout=f,stderr=f,start_new_session=True,stdin=subprocess.DEVNULL)
(b/'development-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time(),'job':job,'scope':'deployment and development only, not final paper results'},indent=2))
print(json.dumps({'pid':p.pid,'condition':condition['condition_id'],'output':str(out)}))
