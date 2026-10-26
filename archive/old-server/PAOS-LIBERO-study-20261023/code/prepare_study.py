"""Freeze one new registered LIBERO comparison before any outcome is generated."""
import hashlib,json,os,shutil,sys,time
from pathlib import Path
R=Path(__file__).resolve().parent.parent
B=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022')
sys.path.insert(0,str(R/'code/protocol'))
import planning

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def snapshot(src,dst):
 dst.mkdir(parents=True,exist_ok=False)
 for p in src.rglob('*'):
  if p.is_symlink() or not p.is_file() or any(x in p.parts for x in ('__pycache__','.git')):continue
  if p.suffix not in ('.py','.json','.md','.yaml','.yml','.toml','.txt'):continue
  if p.stat().st_size>5*1024*1024:continue
  rel=p.relative_to(src);target=dst/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
 return {str(p.relative_to(dst)):sha(p) for p in dst.rglob('*') if p.is_file()}

def main():
 if (R/'manifest.json').exists():raise RuntimeError('registration_exists_no_overwrite')
 parent=json.loads((R/'policies/parent.json').read_text());learned=json.loads((R/'policies/learned.json').read_text())
 assert sha(R/'policies/parent.json')=='f6f0e9b505cfe70bd38a14176651cd554d451e2663560d95f78cf7bac0e251e7'
 assert sha(R/'policies/learned.json')=='cb4c8f6485401337dcf4368b2537c997503ff385713b6800c4af8a28a7059b77'
 assert parent['guidance']==learned['guidance'] and parent['update']!=learned['update']
 source=B/'portable-runtime-20261023/paos/worktrees/memrsi-bounded-v2_2'
 hashes={'workflow':snapshot(source,R/'source'),'paos':snapshot(B/'PhyAgentOS-core',R/'paos-core')}
 (R/'source-snapshot.json').write_text(json.dumps(hashes,indent=2))
 arms={}
 for arm in planning.ARMS:
  policy=planning.policy_for(parent,learned,arm)
  arms[arm]=None if policy is None else f'policies/{arm}.json'
  if policy is not None:(R/arms[arm]).write_text(json.dumps(policy,indent=2)+'\n')
 gpus=[2,3,4,6,7];jobs=[]
 for n,case in enumerate(planning.conditions()):
  for j,arm in enumerate(planning.ARMS):
   jobs.append(dict(case,id=case['condition_id']+'/'+arm,arm=arm,gpu=gpus[(n+j)%5]))
 frozen={str(p.relative_to(R)):sha(p) for sub in ('code','source','paos-core','policies') for p in (R/sub).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
 for name in ('orders.json','budget.json','rsi-provenance.json','source-snapshot.json'):frozen[name]=sha(R/name)
 m=dict(version='LIBERO-five-arm-20261023-v1',registered_at=time.time(),root=str(R),source=str(R/'source'),paos_core=str(R/'paos-core'),histories=list(planning.DEFAULT_HISTORIES),gpus=gpus,jobs=jobs,planned_conditions=24,planned_episodes=120,arm_policies=arms,frozen_files=frozen,call_limit_per_case=480,episode_timeout_seconds=10800,study_timeout_seconds=48*3600,primary_comparisons=list(planning.PRIMARY_COMPARISONS),physical_sampling='Original paired_sampling common random numbers; same seed per task/init/attempt/chunk across arms',scope='New LIBERO-based multi-session mission-order comparison; six registered order histories x two initial states x two kitchen variants, not 24 independent task families and not official whole-suite LIBERO success. Scene init states have historical exposure; combinations were not used for this optimizer training.',rules=['No policy learning during this evaluation','Keep native 19 archive boundaries and all shared token budgets','Rotate arms across GPUs','Keep every method and physical failure, no outcome-based retries','On infrastructure failure stop new dispatch and inspect original logs; no diagnostic study expansion','No combining old and new success counts','RSI treatment changed U automatically; G unchanged; no independent learned-G claim'],rsi_provenance=str(R/'rsi-provenance.json'),stopping_rule='Fixed 120 episodes, no optional stopping by success rate; 48h hard maximum. Infrastructure failures pause without automatic replay.')
 (R/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
 (R/'registration.sha256').write_text(sha(R/'manifest.json')+'\n')
 print(json.dumps({'registered':120,'conditions':24,'gpus':gpus,'manifest_sha256':sha(R/'manifest.json')}))
if __name__=='__main__':main()
