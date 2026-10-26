"""Three continuous missions, native PAOS versus candidate MemRSI, real gripper.
Scene transitions are scheduled; no autonomous navigation claim.
"""
import argparse,asyncio,json,time,itertools
from pathlib import Path
from world_client import World
from run_queue import dump
from runtime_config import usage_totals

def arrange(orders,variant):
 middle=[o for o in orders if not(o.get('benchmark')=='libero_10' and o['task_id'] in [4,6])]
 assert len(middle)==4
 return middle[variant%4:]+middle[:variant%4]

def original(case=None):
 return ('Prepare both service tables. At service table one, put the white mug on the plate and chocolate pudding to the right of the plate. '
         'At service table two, put the white mug on the left plate and yellow-and-white mug on the right plate. '
         'Start with table one, then do table two. Finish after the requested work is complete.')

async def main(a):
 out=Path(a.output);out.mkdir(parents=True,exist_ok=False);start=time.time();agent=None;home1=home2=kitchen=None
 orders=json.loads(Path(a.orders).read_text());middle=arrange(orders,a.variant)*(3 if a.scenario=='long_sessions' else 1)
 table1=next(o for o in orders if o.get('benchmark')=='libero_10' and o['task_id']==6)
 table2=next(o for o in orders if o.get('benchmark')=='libero_10' and o['task_id']==4)
 partial=a.scenario=='unfinished_return';facts={'serve_table_one':False,'serve_table_two':False}
 r={'status':'running','arm':a.arm,'scenario':a.scenario,'init':a.init,'variant':a.variant,'orders':middle,
    'decisions':[],'physical_executions':[],'planned_checkpoint':2 if partial else 1,
    'arrived_checkpoint':0,'answered_checkpoint':0,'correct_checkpoint':0,
    'planned_native_tasks':len(middle)+2,'planned_rollovers':len(middle)//2+int(partial),
    'scope':'Real gripper, native tasks. Externally scheduled scene transitions. Native PAOS persistent memory preserved. MemRSI uses prior failure-derived procedures and actor-authored mission state; no evaluator goals in memory.'}
 runtime_phase={}
 def save(phase,**kw):
  runtime_phase.clear();runtime_phase.update(phase=phase,**kw)
  dump(out/'progress.json',dict(r,phase=phase,updated_unix=time.time(),**kw))
 async def tell(text):
  if agent:await agent.observe_only(text,facts)
 async def choose(text,expected,stage,checkpoint=False):
  save('decision',stage=stage)
  if checkpoint:r['arrived_checkpoint']+=1
  if not agent:choice={'skill':expected,'reason':'physical preflight script'}
  else:
   try:choice=await agent.turn(text,facts,decision=True)
   except RuntimeError as e:
    if str(e)!='action_protocol_failure':raise
    r.setdefault('protocol_repairs',[]).append(stage)
    choice=await agent.turn('Submit exactly one report_action for the same pending decision. No new task is being assigned and no task answer is supplied.',facts,decision=True)
  row={'stage':stage,'choice':choice,'expected':expected,'correct':choice['skill']==expected}
  r['decisions'].append(row)
  if checkpoint:r['answered_checkpoint']+=1;r['correct_checkpoint']+=int(row['correct'])
  with (out/'decisions.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
  if not row['correct']:
   r.update(status='decision_failure',failure='premature_finish' if choice['skill']=='finish' else 'wrong_action',failed_stage=stage)
  return row['correct']
 def execute(w,stage,stop=False):
  save('physical_execution',stage=stage)
  x=w.send(op='execute',stop_after_one=stop)
  r['physical_executions'].append({'stage':stage,'result':x})
  if not x['success']:r.update(status='execution_failure',failure=stage)
  return x
 def prompt(location,w):
  return 'Location: '+location+'. Continue. Scene observation: '+json.dumps(w.send(op='observe')['scene_observation'])+' Choose your next skill.'
 async def feedback(skill,x,extra=None):
  data={'skill':skill,'segment_completed':x['success'],'native_task_complete':x['native_task_complete'],
        'components_observed':x.get('components_after',{}),'scene_observation':x['after']['scene_observation']}
  if extra:data.update(extra)
  await tell('Execution feedback: '+json.dumps(data))
 async def rollover(index):
  if agent:save('session_archive',after_stage=index);await agent.rollover()
 try:
  if a.arm!='reference':
   from agent_adapter import Agent
   agent=Agent(a.arm,out,memory_policy=a.memory_policy)
   r['memory_policy_sha256']=agent.policy_hash if agent.policy else None
  home1=World(out/'table-one',a.port,a.init,table1)
  if not await choose(original()+' '+prompt('service table one',home1),'serve_table_one','table_one_start'):return
  x=execute(home1,'table_one_partial' if partial else 'table_one',partial)
  facts['serve_table_one']=x.get('native_task_complete',False)
  await feedback('serve_table_one',x)
  if not x['success']:return
  if partial and (sum(x['components_after'].values())!=1 or facts['serve_table_one']):
   raise RuntimeError('partial_boundary_invalid')
  first_saved=home1.send(op='observe')
  home2=World(out/'table-two',a.port,a.init,table2);before=home2.send(op='observe');r['table_two_before']=before
  await tell('Please pause the service-table work and handle the kitchen service round first. I will give %d work orders, one at a time. This is a temporary interruption.'%len(middle))
  for index,order in enumerate(middle,1):
   save('initialize_order',order_index=index)
   kitchen=World(out/('order-%02d'%index),a.port,a.init,order);facts['order_'+str(index)]=False
   instruction=json.loads((out/('order-%02d'%index)/'physical/initial.json').read_text())['instruction']
   if not await choose('Location: kitchen work order %d. User request: %s. Scene observation: %s. Choose your next skill.'%(index,instruction,json.dumps(kitchen.initial['scene_observation'])),'execute_order','order_%d'%index):return
   x=execute(kitchen,'order_%d'%index);facts['order_'+str(index)]=x['native_task_complete']
   await feedback('execute_order',x,{'work_order_id':index})
   kitchen.close();kitchen=None
   if not x['success']:return
   if index%2==0:await rollover(index)
  after=home2.send(op='observe');first_after=home1.send(op='observe')
  r['home_states_preserved']=(before['state_sha256']==after['state_sha256'] and before['steps']==after['steps'] and
                            first_saved['state_sha256']==first_after['state_sha256'] and first_saved['steps']==first_after['steps'])
  if not r['home_states_preserved']:raise RuntimeError('preserved_scene_changed')
  if partial:
   if not await choose('The kitchen service round has ended. '+prompt('service table one',home1),'serve_table_one','return_to_unfinished_table_one',True):return
   x=execute(home1,'table_one_resume');facts['serve_table_one']=x['native_task_complete']
   await feedback('serve_table_one',x)
   if not x['success']:return
   await rollover('returned_table_one_completed')
  if not await choose(('The kitchen service round has ended. ' if not partial else '')+prompt('service table two',home2),'serve_table_two','return_to_table_two',True):return
  x=execute(home2,'table_two');facts['serve_table_two']=x['native_task_complete']
  await feedback('serve_table_two',x)
  if not x['success']:return
  if not await choose(prompt('service table two',home2),'finish','mission_finish'):return
  r['status']='success'
 except Exception as e:
  code=str(e);known=['action_protocol_failure','generation_output_limit','provider_error','agent_call_budget_exhausted','native_session_archival_failed','preserved_scene_changed','physics_worker_exited','partial_boundary_invalid']
  r.update(status='protocol_failure' if code in known[:2] else 'infrastructure_failure',error_type=type(e).__name__,error_code=code if code in known else 'runtime_error')
 finally:
  if agent:
   r.update(rollovers=agent.rollovers,model_calls=agent.provider.calls,memory_revisions=agent.memory.revision if a.arm=='memrsi' else None)
   await agent.close()
  for w in [kitchen,home2,home1]:
   if w:w.close()
  r['completed_native_tasks']=sum(int(x['result'].get('native_task_complete',False)) for x in r['physical_executions'])
  r['elapsed_seconds']=time.time()-start;r.update(usage_totals(out))
  r['physical_tasks_all_completed']=r['completed_native_tasks']==r['planned_native_tasks']
  r['failure_phase']=dict(runtime_phase) if r['status']!='success' else None
  dump(out/'result.json',r);save('terminal')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--orders',required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--init',type=int,required=True)
 p.add_argument('--variant',type=int,choices=range(4),default=0);p.add_argument('--scenario',choices=['standard','long_sessions','unfinished_return'],required=True)
 p.add_argument('--arm',choices=['native','memrsi','reference'],required=True);p.add_argument('--memory-policy')
 asyncio.run(main(p.parse_args()))
