import json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
class World:
 def __init__(self,out,port,init,order):
  out=Path(out);out.mkdir(parents=True,exist_ok=False);self.log=(out/'simulation.log').open('w')
  self.p=subprocess.Popen(['/data/songziying/paos-libero-20261023/migration/portable-runtime-20261023/paos/venvs/libero/bin/python','-u',str(ROOT/'native_world.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1)
  try:self.initial=self.send(op='initialize',output=str(out/'physical'),port=port,init=init,suite=order.get('benchmark','libero_90'),task_id=order['task_id'],task_name=order['task_name'])
  except Exception:self.close(force=True);raise
 def send(self,**req):
  self.p.stdin.write(json.dumps(req)+'\n');self.p.stdin.flush();line=self.p.stdout.readline()
  if not line:raise RuntimeError('physics_worker_exited')
  r=json.loads(line)
  if not r['ok']:raise RuntimeError('physics_'+r.get('error_type','error'))
  return r['result']
 def close(self,force=False):
  if self.p.poll() is None:
   try:
    if force:self.p.terminate()
    else:self.send(op='close')
    self.p.wait(timeout=20)
   except Exception:self.p.kill();self.p.wait()
  self.log.close()
