"""Finite live G/U plumbing acceptance; synthetic public history, no physical task score."""
import asyncio,json,sys,time,hashlib
from pathlib import Path
B=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022');P=B/'portable-runtime-20261023'
sys.path[:0]=[str(B/'PhyAgentOS-core'),str(P/'paos/worktrees/memrsi-bounded-v2_2'),str(P/'robot/paper-completion-20261020/guidance-advisor-study-20261022')]
from twenty_agent import TwentyAgent
from base_interventions import ARMS,agent_class
import model_provider
model_provider.CALL_LIMIT=24
from model_provider import MODEL
O=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-validation-20261023/live-gu-probe')
O.mkdir(parents=True,exist_ok=True)
policy=P/'robot/runs/paper-completion-20261020/gu-repair-r2-20261022/frozen-policy.json'
budget={'persistent_tokens':1024,'active_input_tokens':12288,'output_tokens_per_call':2048}
def write(name,data):
 p=O/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(data,indent=2));t.replace(p)
def lines(p):return [json.loads(x) for x in p.read_text().splitlines() if x] if p.exists() else []
async def main():
 assert not (O/'registration.json').exists(), 'probe_already_registered'
 write('registration.json',{'time':time.time(),'arms':ARMS,'model':MODEL,'logical_call_cap_per_arm':24,'physical_calls':0,'scope':'synthetic mechanism acceptance, not task-performance or RSI evidence','input':'Remember public marker PROBE_AMBER_23; no physical work authorized. Submit finish for this interface test.','policy_sha256':hashlib.sha256(policy.read_bytes()).hexdigest()})
 rows=[]
 for arm in ARMS:
  out=O/arm/'attempt-01/agent';a=agent_class(TwentyAgent,arm)('memrsi',out,policy,budget)
  try:
   await a.observe_only('Interface test history: retain marker PROBE_AMBER_23 for a future session. No robot execution is authorized by this test.')
   action=await a.turn('For this interface test submit finish. The public marker remains relevant for the next session. Do not execute physical work.',decision=True)
   await a.observe_only('Interface-test dispatcher receipt: this test executed no robot actions.')
   await a.rollover();await a.rollover()
   traces=lines(out/'model-trace.jsonl');g=u=archive=inject=0
   for t in traces:
    r=t.get('request',{});names={x.get('function',{}).get('name') for x in r.get('tools',[]) or []};txt=json.dumps(r.get('messages',[]))
    g+=('select_memory_evidence' in names);inject+=('# Selected memory evidence' in txt)
    is_u=names in ({'save_memory'},{'pack_storage'});archive+=is_u;u+=is_u and 'Update procedure for the long/short memory interface.' in txt
   memory=(a.workspace/'memory/MEMORY.md').read_text()
   row={'arm':arm,'action':action['skill'],'calls':a.provider.calls,'guidance_requests':g,'guidance_injections':inject,'archive_requests':archive,'custom_update_requests':u,'archive_completed':bool(a.rollovers[-1]['success']),'memory_changed':a.rollovers[-1]['memory_before_sha256']!=a.rollovers[-1]['memory_after_sha256'],'marker_retained':'PROBE_AMBER_23' in memory,'guidance_short_nonempty':any(x['guidance_short_messages']>0 for x in lines(out/'gu-exposure.jsonl'))}
   row['passed']=bool(archive and row['archive_completed'] and row['marker_retained'] and ((g>0 and row['guidance_short_nonempty']) if arm.startswith('g1') else g==0 and inject==0) and (u==archive if arm.endswith('u1') else u==0))
   rows.append(row);write('progress.json',{'phase':'running','rows':rows})
   if not row['passed']:raise RuntimeError('mechanism_acceptance_failed')
  except Exception as e:
   write('result.json',{'phase':'blocked','error_type':type(e).__name__,'arm':arm,'rows':rows});raise
  finally:await a.close()
 write('result.json',{'phase':'passed','scope':'live G/U and native archival plumbing only; no physical evaluation, no learned improvement','rows':rows});print(json.dumps({'phase':'passed','rows':rows}))
asyncio.run(main())
