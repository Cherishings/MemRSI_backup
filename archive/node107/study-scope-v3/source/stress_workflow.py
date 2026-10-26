"""History-dependent ordered table service with actual action-driven dispatch."""
import argparse,asyncio,json,time
from pathlib import Path
from run_queue import dump
from world_client import World
from runtime_config import usage_totals
from pair_protocol import initial_instruction,continuation_input,expected_order,digest
from workflow import arrange
from stress_protocol import protocol, classify_error

async def main(a):
 out=Path(a.output);out.mkdir(parents=True,exist_ok=False);start=time.time();agent=None;kitchen=None;stations={}
 orders=json.loads(Path(a.orders).read_text());middle=arrange(orders,a.variant)*(a.jobs//4)
 plan=protocol(a.case,a.history,a.jobs)
 facts={'serve_table_one':False,'serve_table_two':False}
 r={'status':'running','case':a.case,'arm':a.arm,'history':a.history,'init':a.init,'variant':a.variant,'intermediate_jobs':a.jobs,
    'planned_rollovers':a.jobs//2,'planned_native_tasks':plan['planned_physical_tasks'],'planned_checkpoint':plan['planned_memory_checkpoints'],'arrived_checkpoint':0,
    'answered_checkpoint':0,'correct_checkpoint':0,'first_return_correct':None,'decisions':[],
    'physical_executions':[],'decision_errors':[],
    'scope':'Full native kitchen tasks and real gripper. Agent selects service station; transitions are simulated routing, not autonomous navigation. Matched native/fixed/evolved mission-memory evaluation; task-level success requires correct choices and physical execution. No claim that differing completed scenes are identical.'}
 phase={}
 def save(name,**kw):
  phase.clear();phase.update(phase=name,**kw);dump(out/'progress.json',dict(r,**phase,updated_unix=time.time()))
 def observations():
  return {'station_one':stations['serve_table_one'].send(op='observe')['scene_observation'],
          'station_two':stations['serve_table_two'].send(op='observe')['scene_observation']}
 async def observe(text):
  await agent.observe_only(text,facts)
 async def choose(text,expected,stage,checkpoint=False):
  save('decision',stage=stage)
  if checkpoint:r['arrived_checkpoint']+=1
  c=await agent.turn(text,facts,decision=True)
  row={'stage':stage,'choice':c,'expected':expected,'correct':c['skill']==expected}
  r['decisions'].append(row)
  with (out/'decisions.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
  if checkpoint:
   r['answered_checkpoint']+=1;r['correct_checkpoint']+=int(row['correct'])
   if stage=='return_1':r['first_return_correct']=row['correct']
  if not row['correct']:r['decision_errors'].append({'stage':stage,'skill':c['skill'],'expected':expected})
  return c
 async def dispatch(choice,stage,order_id=None):
  skill=choice['skill']
  if skill=='finish':return None
  # Dispatch uses only the chosen action, never the evaluator's expected action.
  if skill in stations:w=stations[skill];fact_key=skill
  elif skill=='execute_order' and kitchen is not None:w=kitchen;fact_key='order_'+str(order_id)
  else:
   r.update(status='decision_failure',failure='no_current_work_order');return None
  save('physical_execution',stage=stage,selected_skill=skill)
  partial=stage.startswith('initial_service_') and plan.get('partial_initial') and skill=='serve_table_one'
  x=w.send(op='execute',stop_after_one=bool(partial));facts[fact_key]=x['native_task_complete']
  r['physical_executions'].append({'stage':stage,'skill':skill,'work_order_id':order_id,'result':x})
  from execution_contract import receipt
  info=receipt(skill,x)
  if skill=='execute_order':info['work_order_id']=order_id
  await observe('Execution feedback: '+json.dumps(info))
  if not x['success']:
   r.update(status='decision_failure' if r['decision_errors'] else 'execution_failure',failure='execution_after_wrong_choice' if r['decision_errors'] else stage)
  return x
 try:
  from agent_adapter import Agent
  agent=Agent(a.arm,out,memory_policy=a.memory_policy)
  r['memory_policy_sha256']=agent.policy_hash if agent.policy else None
  for skill,tid,label in [('serve_table_one',6,'station-one'),('serve_table_two',4,'station-two')]:
   order=next(o for o in orders if o.get('benchmark')=='libero_10' and o['task_id']==tid)
   stations[skill]=World(out/label,a.port,a.init,order)
  initial={s:w.send(op='observe') for s,w in stations.items()}
  dump(out/'protocol.json',plan)
  await observe(plan['initial'])
  seen=set()
  for slot,target in enumerate(plan['pre_actions']):
   c=await choose('Start the initial partial placement at table one now. Pause after its first object is safely placed; the kitchen work orders have not started. Current scene observations: '+json.dumps(observations(),sort_keys=True),target,'initial_service_%d'%slot)
   x=await dispatch(c,'initial_service_%d'%slot)
   if c['skill']!=target:r.update(status='decision_failure',failure='wrong_initial_service');return
   if x is None or not x['success']:return
   if x['native_task_complete']:seen.add(c['skill'])
  # Record the actual partially completed world, not a reset to the initial state.
  preserved={s:w.send(op='observe') for s,w in stations.items()}
  await observe(plan['interruption'])
  for idx,order in enumerate(middle,1):
   save('initialize_order',order_index=idx)
   kitchen=World(out/('order-%02d'%idx),a.port,a.init,order);facts['order_'+str(idx)]=False
   instruction=json.loads((out/('order-%02d'%idx)/'physical/initial.json').read_text())['instruction']
   c=await choose('Kitchen work order %d: %s. Current scene observation: %s'%(idx,instruction,json.dumps(kitchen.initial['scene_observation'])),'execute_order','order_%d'%idx)
   x=await dispatch(c,'order_%d'%idx,idx)
   kitchen.close();kitchen=None
   if c['skill']!='execute_order':r.update(status='decision_failure',failure='wrong_action_during_interruption');return
   if x is None or not x['success']:return
   if idx in plan['updates_after_order']:
    await observe(plan['updates_after_order'][idx])
   if idx%2==0:
    save('session_archive',after_order=idx);await agent.rollover()
  saved={s:w.send(op='observe') for s,w in stations.items()}
  if any(saved[s]['state_sha256']!=preserved[s]['state_sha256'] or saved[s]['steps']!=preserved[s]['steps'] for s in stations):
   raise RuntimeError('preserved_scene_changed')
  current=continuation_input(observations())
  snapshot={'current_input':current,'current_input_sha256':digest(current),
            'station_state_sha256':{s:d['state_sha256'] for s,d in saved.items()},
            'station_steps':{s:d['steps'] for s,d in saved.items()},'location_hint':None}
  snapshot['expected_first_private']=plan['expected_remaining'][0] if plan['expected_remaining'] else 'finish'
  snapshot['action_contract_sha256']=digest(__import__('agent_adapter').COMMON_TOOLS)
  r['recovery_snapshot']=snapshot;dump(out/'recovery-snapshot.json',snapshot)
  expected=plan['expected_remaining']
  cancelled=set(expected_order(a.history)[1:]) if a.case=='cancel' else set()
  for slot in range(len(expected)+1):
   target=expected[slot] if slot<len(expected) else 'finish'
   c=await choose(current,target,'return_%d'%(slot+1) if slot<len(expected) else 'finish',checkpoint=True)
   if c['skill']!=target:
    r.setdefault('memory_error_forms',[]).append(classify_error(c['skill'],target,seen,cancelled))
   if c['skill']=='finish':
    if slot<len(expected):r.update(status='decision_failure',failure='premature_finish')
    else:r.update(status='decision_failure' if r['decision_errors'] else 'success',failure='wrong_service_order' if r['decision_errors'] else None)
    break
   if c['skill'] in seen:
    r.update(status='decision_failure',failure='duplicate_service_action');break
   x=await dispatch(c,'selected_station_%d'%(slot+1))
   seen.add(c['skill'])
   if x is None or not x['success']:break
   if slot==len(expected):r.update(status='decision_failure',failure='did_not_stop_after_completion');break
   current=continuation_input(observations())
 except Exception as e:
  code=str(e);protocol_errors={'action_protocol_failure','generation_output_limit','guidance_protocol_failure'}
  known=protocol_errors|{'provider_error','agent_call_budget_exhausted','native_session_archival_failed','preserved_scene_changed','physics_worker_exited','model_admission_wait_timeout'}
  r.update(status='protocol_failure' if code in protocol_errors else 'infrastructure_failure',error_type=type(e).__name__,error_code=code if code in known else 'runtime_error')
 finally:
  if agent:
   r.update(rollovers=agent.rollovers,model_calls=agent.provider.calls,memory_revisions=getattr(getattr(agent,'memory',None),'revision',None) if a.arm=='memrsi' else None)
   await agent.close()
  for w in [kitchen]+list(stations.values()):
   if w:w.close()
  r['completed_native_tasks']=sum(int(v) for v in facts.values())
  r['physical_tasks_all_completed']=r['completed_native_tasks']==r['planned_native_tasks']
  r['elapsed_seconds']=time.time()-start;r.update(usage_totals(out))
  r['failure_phase']=dict(phase) if r['status']!='success' else None
  from portable_metrics import normalize_libero
  dump(out/'metric-record.json',normalize_libero(r))
  dump(out/'result.json',r);save('terminal')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--orders',required=True);p.add_argument('--port',type=int,required=True)
 p.add_argument('--init',type=int,required=True);p.add_argument('--variant',type=int,choices=[0,1],required=True);p.add_argument('--jobs',type=int,choices=[12,16,24,32],required=True)
 p.add_argument('--case',choices=['resume','delay','revise','cancel'],required=True);p.add_argument('--history',choices=['one_first','two_first'],required=True);p.add_argument('--arm',choices=['native','memrsi'],required=True);p.add_argument('--memory-policy')
 asyncio.run(main(p.parse_args()))
