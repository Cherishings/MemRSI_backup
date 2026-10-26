"""One registered LIBERO lane. No training, retries, or answer-derived dispatch."""
import argparse,asyncio,hashlib,json,os,sys,time,traceback
from pathlib import Path
from types import SimpleNamespace

def write(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name(path.name+f'.{os.getpid()}.tmp');temp.write_text(json.dumps(value,indent=2,ensure_ascii=False));temp.replace(path)
def verify(root,manifest):
 for rel,sha in manifest['frozen_files'].items():
  if hashlib.sha256((root/rel).read_bytes()).hexdigest()!=sha:raise RuntimeError('frozen_input_changed:'+rel)
async def main(a):
 root=Path(a.root);m=json.loads((root/'manifest.json').read_text());verify(root,m)
 registration=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
 assert registration==(root/'registration.sha256').read_text().strip()
 gpu=a.gpu;port=20500+gpu
 sys.path[:0]=[str(root/'code/runtime'),str(root/'code/protocol')]
 import runtime_adapter
 runtime_adapter.configure(gpu=gpu,port=port,core_path=m['paos_core'])
 import twenty_agent,feedback_workflow,model_provider
 import planning,twenty_protocol
 feedback_workflow.plan=planning.bind_registered_plan(twenty_protocol.plan,m['histories'])
 Base=twenty_agent.TwentyAgent
 model_provider.CALL_LIMIT=m['call_limit_per_case']
 outcomes=[]
 for job in m['jobs']:
  if job['gpu']!=gpu:continue
  if (root/'STOP').exists():break
  verify(root,m)
  if hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()!=registration:raise RuntimeError('registration_changed')
  dest=root/'cases'/job['id']
  if dest.exists():raise RuntimeError('existing_case_requires_audit:'+job['id'])
  active_arm=job['arm'];policy=m['arm_policies'][active_arm]
  expected=json.loads((root/policy).read_text()) if policy else None
  twenty_agent.TwentyAgent=planning.bind_agent_class(Base,active_arm,expected)
  kwargs=dict(output=str(dest),orders=str(root/'orders.json'),port=port,init=job['init'],variant=job['variant'],history=job['history'],arm='native' if policy is None else 'memrsi',budget=str(root/'budget.json'),memory_policy=str(root/policy) if policy else None)
  write(root/f'lane-gpu{gpu}.json',{'phase':'running','job':job,'time':time.time(),'pid':os.getpid()})
  result=await feedback_workflow.run(SimpleNamespace(**kwargs))
  method_codes={'native_session_archival_failed','agent_call_budget_exhausted','guidance_review_protocol_failure','guidance_protocol_failure','action_protocol_failure','persistent_memory_budget_exhausted','active_context_budget_exceeded','generation_output_limit'}
  result['registered_failure_class']='method_failure' if result.get('error_code') in method_codes else ('infrastructure_failure' if result['status']=='infrastructure_failure' else result['status'])
  result.update(registered_arm=active_arm,condition_id=job['condition_id'],hardware_gpu=gpu,physical_model='pi05_libero',attempt=1,registration_sha256=registration)
  write(dest/'result.json',result)
  outcomes.append({'id':job['id'],'status':result['status']})
  write(root/f'lane-gpu{gpu}.json',{'phase':'between_cases','completed':outcomes,'time':time.time(),'pid':os.getpid()})
  if result['registered_failure_class']=='infrastructure_failure':
   write(root/'blocked.json',{'reason':'infrastructure_failure','job':job,'result':result,'no_automatic_retry':True});(root/'STOP').touch();return
 write(root/f'lane-gpu{gpu}.json',{'phase':'stopped' if (root/'STOP').exists() else 'completed','completed':outcomes,'time':time.time(),'pid':os.getpid()})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--gpu',type=int,required=True);a=p.parse_args()
 try:asyncio.run(main(a))
 except BaseException as e:
  root=Path(a.root);write(root/'blocked.json',{'reason':'lane_exception','gpu':a.gpu,'error_type':type(e).__name__,'error':str(e)[:250]});(root/'STOP').touch();raise
