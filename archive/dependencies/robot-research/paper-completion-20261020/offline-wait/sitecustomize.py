"""Apply audited transport-only override to matching frozen provider imports."""
import importlib.machinery,hashlib,json,os
from pathlib import Path
if os.environ.get('MEMRSI_OFFLINE_WAIT')=='1':
 original=importlib.machinery.SourceFileLoader.exec_module
 def execute(self,module):
  original(self,module)
  if module.__name__=='learning_budget' and os.environ.get('MEMRSI_PARALLEL_BUDGET')=='1':
   root=Path(__file__).resolve().parent;allowed=json.loads((root/'allowed-learning-budget.json').read_text());path=str(Path(module.__file__).resolve());digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
   if allowed.get(path)!=digest:raise RuntimeError('parallel_budget_source_hash_mismatch')
   from parallel_budget import install_charge
   install_charge(module)
  if module.__name__=='model_provider':
   root=Path(__file__).resolve().parent
   allowed=json.loads((root/'allowed-providers.json').read_text())
   path=str(Path(module.__file__).resolve());digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
   if allowed.get(path)!=digest:raise RuntimeError('offline_transport_source_hash_mismatch')
   from transport_wait_override import install
   install(module)
 importlib.machinery.SourceFileLoader.exec_module=execute
 # Frozen launchers explicitly replace PYTHONPATH; propagate only this
 # operational hook through their child environments without editing sources.
 import subprocess
 _Popen=subprocess.Popen
 class OfflineWaitPopen(_Popen):
  def __init__(self,*args,**kwargs):
   env=kwargs.get('env')
   if env is not None and env.get('MEMRSI_OFFLINE_WAIT')=='1':
    env=dict(env);hook=str(Path(__file__).resolve().parent)
    entries=env.get('PYTHONPATH','').split(os.pathsep)
    if hook not in entries:env['PYTHONPATH']=os.pathsep.join([hook]+[x for x in entries if x])
    kwargs['env']=env
   if os.environ.get('MEMRSI_PARALLEL_BUDGET')=='1':
    cmd=kwargs.get('args',args[0] if args else None)
    if isinstance(cmd,(list,tuple)) and len(cmd)>1 and str(cmd[1]) in ['/data/stormlab/xi/robot/official-memory-v5r3-20261018/run_trial.py','/data/stormlab/xi/robot/official-memory-v5r4-20261018/run_trial.py']:
     cmd=list(cmd);code=str(Path(cmd[1]).parent);cmd[1:2]=[str(Path(__file__).resolve().parent/'trial_entry.py'),code]
     if 'args' in kwargs:kwargs['args']=cmd
     else:args=(cmd,)+args[1:]
   super().__init__(*args,**kwargs)
 subprocess.Popen=OfflineWaitPopen
