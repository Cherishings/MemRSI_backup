import argparse,asyncio,json,time
from pathlib import Path
from run_queue import dump
from world_client import World
from workflow import arrange
from twenty_protocol import plan,restore_input,digest,TABLES,TOOLS
from execution_contract import receipt
from runtime_config import usage_totals

async def run(a):
 out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
 p=plan(a.history);dump(out/'protocol-private.json',p)
 orders=json.loads(Path(a.orders).read_text());middle=arrange(orders,a.variant)
 task6=next(x for x in orders if x.get('benchmark')=='libero_10' and x['task_id']==6)
 task4=next(x for x in orders if x.get('benchmark')=='libero_10' and x['task_id']==4)
 r={'status':'running','history':a.history,'arm':a.arm,'init':a.init,'variant':a.variant,'planned_sessions':20,'planned_switches':19,
    'sessions_completed':0,'planned_checkpoints':7,'reached_checkpoints':0,'answered_checkpoints':0,'correct_checkpoints':0,
    'decisions':[],'physical_executions':[],'snapshot_checks':[],'partial_successes':0,'recovery_successes':0,
    'scope':'serial real simulated gripper, preserved native tables; program scene routing, no navigation claim',
    'reference_only':a.arm=='reference'}
 agent=None;tables={};job=None;phase={};jobidx=0;finished=set();first_snap=None;started=time.time()
 def save(name,**fields):
  phase.clear();phase.update(phase=name,**fields);dump(out/'progress.json',dict(r,**phase,updated_unix=time.time()))
 def views():return {k:w.send(op='observe')['scene_observation'] for k,w in tables.items()}
 def snapshot():return {k:w.send(op='observe') for k,w in tables.items()}
 async def tell(text):
  if agent:await agent.observe_only(text)
 async def choice(text,target,session,checkpoint):
  save('decision',session=session,expected_hidden=True)
  if checkpoint:r['reached_checkpoints']+=1
  c=await agent.turn(text,decision=True) if agent else {'skill':target,'reason':'private physical reference, not agent evidence'}
  correct=c['skill']==target;r['decisions'].append({'session':session,'skill':c['skill'],'expected_private':target,'correct':correct,'checkpoint':checkpoint})
  if checkpoint:r['answered_checkpoints']+=1;r['correct_checkpoints']+=int(correct)
  return c['skill'],correct
 try:
  if a.arm!='reference':
   from twenty_agent import TwentyAgent
   agent=TwentyAgent(a.arm,out,a.memory_policy,Path(a.budget))
  for k in TABLES+('F','G'):tables['serve_'+k]=World(out/('table-'+k),a.port,a.init,task6 if k in TABLES else task4)
  await tell(p['initial_message'])
  for step in p['sessions']:
   s,kind,target=step['session'],step['kind'],step['expected_private'];before=snapshot()
   if kind=='partial':text='For this current job, begin table '+target[-1]+', then pause as soon as one object is safely placed. Current scenes: '+json.dumps(views(),sort_keys=True)
   elif kind=='kitchen':
    order=middle[jobidx%len(middle)];jobidx+=1;save('initialize_kitchen',session=s)
    job=World(out/f'kitchen-{jobidx:02d}',a.port,a.init,order)
    ins=json.loads((out/f'kitchen-{jobidx:02d}/physical/initial.json').read_text())['instruction']
    text=f'Current kitchen work order {jobidx}: {ins}. Current scene: '+json.dumps(job.initial['scene_observation'])
   else:
    if kind=='recovery' and first_snap is None:
     first_snap=snapshot();dump(out/'first-recovery-scene.json',first_snap)
     r['recovery_snapshot']={'current_input_sha256':digest(restore_input(views())),'station_state_sha256':{k:v['state_sha256'] for k,v in first_snap.items()},'action_contract_sha256':digest(TOOLS),'expected_first_private':target}
    text=restore_input(views())
   skill,correct=await choice(text,target,s,kind in ('recovery','closing'))
   if skill=='finish':r.update(status='decision_failure',failure='premature_finish');break
   if skill in finished:r.update(status='decision_failure',failure='requested_completed_task');break
   w=tables.get(skill) if skill!='execute_order' else job
   if w is None:r.update(status='decision_failure',failure='no_current_job');break
   selected_partial=(kind=='partial' and skill==target)
   save('physical_execution',session=s,skill=skill)
   result=w.send(op='execute',stop_after_one=selected_partial)
   r['physical_executions'].append({'session':s,'skill':skill,'result':result})
   info=receipt(skill,result);await tell('Execution feedback: '+json.dumps(info))
   if result['native_task_complete'] and skill!='execute_order':finished.add(skill)
   if job:job.close();job=None
   if not result['success']:r.update(status='execution_failure',failure=f'session_{s}');break
   if kind=='partial' and correct:
    if result['native_task_complete'] or sum(result['components_after'].values())!=1:raise RuntimeError('partial_boundary_invalid')
    r['partial_successes']+=1
   if kind=='recovery' and correct and result['native_task_complete']:r['recovery_successes']+=1
   after=snapshot()
   unchanged=all(before[k]['state_sha256']==after[k]['state_sha256'] and before[k]['steps']==after[k]['steps'] for k in tables if k!=skill)
   r['snapshot_checks'].append({'session':s,'unselected_tables_unchanged':unchanged})
   if not unchanged:raise RuntimeError('preserved_scene_changed')
   if not correct:r.update(status='decision_failure',failure='cancelled_task' if skill=='serve_G' else 'wrong_task_or_order');break
   if s in p['updates_after_session']:await tell(p['updates_after_session'][s])
   r['sessions_completed']=s
   if s<20:
    save('session_archive',session=s)
    if agent:await agent.rollover()
   else:
    skill,correct=await choice(restore_input(views()),'finish',s,True)
    r.update(status='success' if correct else 'decision_failure',failure=None if correct else 'extra_or_cancelled_work_after_completion')
  if agent:r['rollovers']=agent.rollovers
 except Exception as e:
  code=str(e);allowed={'provider_error','native_session_archival_failed','guidance_protocol_failure','guidance_review_protocol_failure','guidance_grounding_failure','action_protocol_failure','agent_call_budget_exhausted','persistent_memory_budget_exhausted','active_context_budget_exceeded','preserved_scene_changed','partial_boundary_invalid','model_admission_wait_timeout','generation_output_limit'}
  status='guidance_failure' if code == 'guidance_grounding_failure' else 'budget_failure' if code in {'persistent_memory_budget_exhausted','active_context_budget_exceeded'} else 'protocol_failure' if code in {'guidance_protocol_failure','guidance_review_protocol_failure','guidance_grounding_failure','action_protocol_failure','generation_output_limit'} else 'infrastructure_failure'
  r.update(status=status,error_code=code if code in allowed else 'runtime_error',error_type=type(e).__name__)
 finally:
  if agent:r['rollovers']=agent.rollovers;await agent.close()
  if job:job.close()
  for w in tables.values():w.close()
  r.update(elapsed_seconds=time.time()-started,failure_phase=phase if r['status']!='success' else None)
  if agent:r.update(usage_totals(out))
  dump(out/'result.json',r);save('terminal')
 return r

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--orders',required=True)
 parser.add_argument('--port',required=True,type=int);parser.add_argument('--init',type=int,default=0);parser.add_argument('--variant',type=int,default=0)
 parser.add_argument('--history',choices=['alpha','beta'],required=True);parser.add_argument('--arm',choices=['native','memrsi','reference'],required=True)
 parser.add_argument('--budget');parser.add_argument('--memory-policy')
 asyncio.run(run(parser.parse_args()))
