"""Four fixed component interventions; 48 Casa conditions each, no learning."""
import argparse,asyncio,copy,hashlib,importlib.util,json,os,subprocess,time
from pathlib import Path

ARMS=['no_guidance','native_update_rule','no_cross_session_memory','no_short_input_to_guidance']
def agent_class(base,arm):
 class Ablated(base):
  def __init__(self,*args,**kwargs):
   super().__init__(*args,**kwargs)
   if arm=='no_guidance':self.ops=None
   elif arm=='native_update_rule':
    self.provider.memory_policy=copy.deepcopy(self.provider.memory_policy);self.provider.memory_policy['update']=''
   elif arm=='no_short_input_to_guidance':
    original=self.ops.guide
    async def no_short(short,current):return await original([],current)
    self.ops.guide=no_short
   self._write('component-intervention.json',{'arm':arm,'all_other_components_frozen':True,'scoring_unchanged':True})
  async def rollover(self):
   await super().rollover()
   if arm=='no_cross_session_memory':
    evidence=[]
    for name in ['MEMORY.md','HISTORY.md']:
     p=self.workspace/'memory'/name;raw=p.read_bytes() if p.exists() else b''
     evidence.append({'file':name,'before_sha256':hashlib.sha256(raw).hexdigest(),'removed_bytes':len(raw)})
     if p.exists():p.write_text('')
    self._write('boundary-ablation-'+str(len(self.rollovers))+'.json',{'removed':evidence,'native_archive_executed_before_intervention':True,'short_session_already_reset_by_native':True})
 return Ablated

def main():
 p=argparse.ArgumentParser();p.add_argument('--gpu',type=int,choices=[4,7],required=True);p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output)
 spec=importlib.util.spec_from_file_location('cap','/data/stormlab/xi/robot/paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
 manifest=cap.read(out/'manifest.json');source=manifest['source'];core=manifest['core']
 assert cap.file_sha(__file__)==manifest['wrapper_sha256']
 assert cap.source_identity(source,core)==manifest['source_identity']
 engine=cap.load_engine(source,core);base=engine.TwentyAgent
 from setproctitle import setproctitle
 setproctitle('robot');me=cap.identity();wp=out/f'worker-gpu{a.gpu}.json'
 with cap.locked(out/f'worker-gpu{a.gpu}.lock',nonblocking=True):
  while not engine.STOP.is_set() and time.time()<manifest['start_before_epoch']:
   with cap.locked(out/'dispatch.lock'):
    if (out/'blocked.json').exists():return
    claims=cap.read(out/'claims.json',{});job=None
    for item in manifest['jobs']:
     if (out/item['key']/'result.json').exists():continue
     if item['key'] in claims:
      if not cap.alive(claims[item['key']]['identity']):
       cap.write(out/'blocked.json',{'reason':'interrupted_claim_requires_audit','key':item['key']});return
      continue
     job=item;claims[job['key']]={'identity':me,'gpu':a.gpu};cap.write(out/'claims.json',claims);break
   if job is None:cap.write(wp,{'phase':'completed','identity':me});return
   arm=job['arm'];case=out/job['key'];trial=case/'attempt-01'
   if trial.exists():raise RuntimeError('prior_attempt_requires_audit')
   def state(phase):cap.write(wp,{'phase':phase,'case':job['key'],'identity':me,'gpu':a.gpu,'time':time.time()})
   engine.gateway_contract(engine.STOP,lambda:state('waiting_gateway'))
   used=lambda:int(subprocess.check_output(['nvidia-smi','-i',str(a.gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
   state('waiting_gpu')
   with engine.acquire(engine.LEASES/engine.lock_name(a.gpu),True,used):
    if time.time()>=manifest['start_before_epoch'] or engine.STOP.is_set():return
    assert cap.source_identity(source,core)==manifest['source_identity']
    engine.TwentyAgent=agent_class(base,arm);state('trial')
    row=asyncio.run(engine.trial(job['plan'],'memrsi',cap.read(out/'frozen-policy.json'),a.gpu,trial))
   final=dict(row,component_ablation=arm,attempt=1,source_policy_sha256=manifest['policy_sha256'],score_unchanged=True)
   cap.write(case/'result.json',final);state('case_finished')
   if row['status']=='technical_failure' or row.get('error_code')=='unclassified_exception':
    with cap.locked(out/'dispatch.lock'):cap.write(out/'blocked.json',{'reason':'technical_failure_requires_audit','key':job['key'],'error_code':row.get('error_code')})
    return
if __name__=='__main__':main()
