import sys
sys.path.insert(0, '/data/stormlab/xi/robot/paper-completion-20261020/guidance-advisor-study-20261022')
"""Finite registered four-arm diagnostic queue. First technical failure pauses."""
import argparse, asyncio, hashlib, importlib.util, json, os, subprocess, time
from pathlib import Path
from interventions import agent_class
from recovery_gate import inspect

from worker import verify

def main():
 p=argparse.ArgumentParser();p.add_argument('--gpu',type=int,choices=[1,2,3,4,5,6,7],required=True);p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output)
 spec=importlib.util.spec_from_file_location('cap','/data/stormlab/xi/robot/paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
 manifest=cap.read(out/'manifest.json');source=manifest['source'];core=manifest['core']
 import sys
 sys.path.insert(0,str(core))
 verify(cap,out,manifest)
 assert cap.source_identity(source,core)==manifest['source_identity']
 engine=cap.load_engine(source,core);base=engine.TwentyAgent
 from setproctitle import setproctitle
 setproctitle('robot');me=cap.identity();wp=out/f'worker-gpu{a.gpu}.json'
 with cap.locked(out/f'worker-gpu{a.gpu}.lock',nonblocking=True):
  while not engine.STOP.is_set() and time.time()<manifest['start_before_epoch']:
   with cap.locked(out/'dispatch.lock'):
    if (out/'blocked.json').exists():return
    claims=cap.read(out/'claims.json',{});job=None
    gate=cap.read(out/'contract-gate.json',{})
    if gate.get('state')!='passed':
     gate=inspect(out,manifest['jobs'][:4]);cap.write(out/'contract-gate.json',gate)
     if gate['state']=='blocked':
      cap.write(out/'blocked.json',{'reason':'information_flow_acceptance_requires_audit','gate':gate});return
    eligible=manifest['jobs'] if gate.get('state')=='passed' else manifest['jobs'][:8]
    for item in eligible:
     if (out/item['key']/'result.json').exists():continue
     if item['key'] in claims:
      if not cap.alive(claims[item['key']]['identity']):
       cap.write(out/'blocked.json',{'reason':'interrupted_claim_requires_audit','key':item['key']});return
      continue
     job=item;claims[job['key']]={'identity':me,'gpu':a.gpu};cap.write(out/'claims.json',claims);break
   if job is None:
    if gate.get('state')!='passed':
     cap.write(wp,{'phase':'waiting_contract_gate','identity':me});time.sleep(10);continue
    cap.write(wp,{'phase':'completed','identity':me});return
   arm=job['arm'];case=out/job['key'];trial=case/'attempt-01'
   if trial.exists():raise RuntimeError('prior_attempt_requires_audit')
   def state(phase):cap.write(wp,{'phase':phase,'case':job['key'],'identity':me,'gpu':a.gpu,'time':time.time()})
   engine.gateway_contract(engine.STOP,lambda:state('waiting_gateway'))
   used=lambda:int(subprocess.check_output(['nvidia-smi','-i',str(a.gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
   state('waiting_gpu')
   with engine.acquire(engine.LEASES/engine.lock_name(a.gpu),True,used):
    if time.time()>=manifest['start_before_epoch'] or engine.STOP.is_set():return
    assert cap.source_identity(source,core)==manifest['source_identity']
    verify(cap,out,manifest)
    engine.TwentyAgent=agent_class(base,arm);state('trial')
    row=asyncio.run(engine.trial(job['plan'],'memrsi',cap.read(out/'frozen-policy.json'),a.gpu,trial))
   final=dict(row,gu_factorial=arm,attempt=1,source_policy_sha256=manifest['policy_sha256'],score_unchanged=True,replicate_block=manifest['replicate_block'],intervention_code_sha256=manifest['code_sha256'],effective_policy_sha256=manifest['effective_policy_sha256'][arm],manual_design_not_RSI=True)
   cap.write(case/'result.json',final);state('case_finished')
   if row['status']=='technical_failure' or row.get('error_code')=='unclassified_exception':
    with cap.locked(out/'dispatch.lock'):cap.write(out/'blocked.json',{'reason':'technical_failure_requires_audit','key':job['key'],'error_code':row.get('error_code')})
    return
if __name__=='__main__':main()
