"""Finish documented configuration and run isolated smoke tests after downloads/install."""
import json,os,subprocess,time,shutil,hashlib
from pathlib import Path
ROOT=Path('/data/stormlab/xi/robot');os.umask(0o077)
def save(name,data):
 p=ROOT/'setup'/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(data,indent=2));t.replace(p)
def run(name,args,cwd=None,timeout=600):
 with (ROOT/'logs'/f'{name}.log').open('a') as f:
  p=subprocess.run([str(x) for x in args],cwd=cwd,stdout=f,stderr=f,timeout=timeout,env=dict(os.environ,PYNPUT_BACKEND='dummy',MUJOCO_GL='egl'))
 if p.returncode:raise RuntimeError(f'{name}: exit {p.returncode}')
def phase(name,p,**more):save(f'ready-{name}.json',dict(phase=p,time=time.time(),**more))
def prepare(name):
 prefix=ROOT/'envs'/name;py=prefix/'bin/python'
 if name=='casa':
  repo=ROOT/'src/robocasa'
  m=repo/'robocasa/macros_private.py'
  if not m.exists():shutil.copy2(repo/'robocasa/macros.py',m)
 else:
  repo=ROOT/'src/RoboTwin'
  index=json.loads((ROOT/'setup/official-asset-index.json').read_text())
  verified=[]
  for item in index:
   if item.get('path') not in ['objects.zip','embodiments.zip','background_texture.zip']: continue
   archive=ROOT/'cache'/('twin-'+item['path'])
   sha=hashlib.sha256()
   with archive.open('rb') as f:
    for block in iter(lambda:f.read(8*1024*1024),b''):sha.update(block)
   assert sha.hexdigest()==item['lfs']['oid'], 'official asset checksum mismatch: '+item['path']
   verified.append({'asset':item['path'],'sha256':sha.hexdigest()})
  save('twin-assets-verified.json',verified)
  patch_log=[]
  for rel,old,new in [
   ('lib/python3.10/site-packages/mplib/planner.py','if np.linalg.norm(delta_twist) < 1e-4 or collide or not within_joint_limit:',
    'if np.linalg.norm(delta_twist) < 1e-4 or not within_joint_limit:'),
   ('lib/python3.10/site-packages/sapien/wrapper/urdf_loader.py','open(urdf_file, "r")','open(urdf_file, "r", encoding="utf-8")'),
   ('lib/python3.10/site-packages/sapien/wrapper/urdf_loader.py','open(srdf_file, "r")','open(srdf_file, "r", encoding="utf-8")')]:
   p=prefix/rel
   if not p.exists():raise RuntimeError('documented_patch_target_missing:'+rel)
   s=p.read_text()
   if old in s:
    backup=p.with_suffix(p.suffix+'.upstream')
    if not backup.exists():shutil.copy2(p,backup)
    p.write_text(s.replace(old,new));patch_log.append({'path':str(p),'change':old+' -> '+new})
   elif new not in s:patch_log.append({'path':str(p),'status':'pattern absent; inspect version'})
  save('documented-twin-patches.json',patch_log)
  run('twin-embodiment-paths',[py,repo/'scripts/update_embodiment_config_path.py'],repo)
 run(f'{name}-pip-final-check',[py,'-m','pip','check'])
 freeze=subprocess.run([str(py),'-m','pip','freeze'],capture_output=True,text=True,check=True)
 (ROOT/'setup'/f'{name}-requirements.lock.txt').write_text(freeze.stdout)
 # Only one lightweight smoke process at a time, using authorized GPU0.
 run(f'{name}-smoke',[ROOT/'bin/robot',name,'0',ROOT/'setup'/f'smoke_{name}.py'],repo,timeout=600)
 result=json.loads((ROOT/'runs'/f'{name}-smoke/result.json').read_text())
 assert result['status']=='passed'
 phase(name,'ready',validation=result)

def main():
 pending={'twin','casa'}
 deadline=time.time()+24*3600
 while pending and time.time()<deadline:
  for name in sorted(pending.copy()):
   p=ROOT/'setup'/f'install-{name}.json'
   if not p.exists():continue
   install=json.loads(p.read_text())
   if install.get('phase')=='failed':
    phase(name,'blocked_install',detail=install);pending.remove(name);continue
   if install.get('phase')!='packages_installed':
    phase(name,'waiting_packages',step=install.get('phase'));continue
   assets=[json.loads(p.read_text()) for p in (ROOT/'setup').glob(f'asset-{name}-*.json')]
   expected=3 if name=='twin' else 6
   if len(assets)!=expected or any(a.get('phase')!='complete' for a in assets):
    phase(name,'waiting_assets',complete=sum(a.get('phase')=='complete' for a in assets),total=expected);continue
   phase(name,'validating')
   try:prepare(name)
   except Exception as e:phase(name,'blocked_validation',error=str(e))
   pending.remove(name)
  if pending:time.sleep(30)
 for name in pending:phase(name,'incomplete_timeout')
 save('finalizer-exit.json',{'time':time.time()})
if __name__=='__main__':main()
