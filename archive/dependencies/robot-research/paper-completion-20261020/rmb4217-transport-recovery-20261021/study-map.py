"""Two exact audited cache mappings; all other cases use frozen study.one."""
import sys,importlib.util
from pathlib import Path
NATIVE='8141d8e412607feec08f7a93430869e0cb2ca8dea2604af8f11b5fc645ea9636'
INITIAL='5fd015e03e5258978c2f09104dcdf89224187cce23253e8e268139bb229140f0'
def install(m):
 original=m.one
 def one(a,phase,method,policy,seed):
  ph=m.policy_sha256(m.read(policy)) if method!='native' else m.run_trial.native_policy_hash()
  mapped=(a.benchmark=='rmbench' and ((phase=='development' and seed==4000 and method!='native' and ph==INITIAL) or (phase=='test' and seed==4217 and method=='native' and ph==NATIVE)))
  if mapped:
   folder=a.output/'trajectories'/phase/ph/(str(seed)+'-attempt02')
   row=m.checked_cached_row(a,phase,method,ph,seed,folder)
   return dict(row,method=method),folder
  return original(a,phase,method,policy,seed)
 m.one=one
if __name__=='__main__':
 code=Path(sys.argv.pop(1));sys.path.insert(0,str(code));spec=importlib.util.spec_from_file_location('frozen_study',code/'run_study.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);install(m);m.main()
