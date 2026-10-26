"""Own five GPU lanes and stop cleanly; fixed registration, no adaptive experiments."""
import fcntl,hashlib,json,os,signal,socket,subprocess,sys,time,concurrent.futures
from pathlib import Path
R=Path(__file__).resolve().parent.parent;B=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022')
sys.path.insert(0,str(R/'code/runtime'))
from libero_runtime import lane_env,policy_command
from study_worker import verify,write
children=[];locks=[];stopping=False

def identity(pid):return {'pid':pid,'start_ticks':Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]}
def stop(*_):
 global stopping
 stopping=True;(R/'STOP').touch()
for s in (signal.SIGINT,signal.SIGTERM):signal.signal(s,stop)
def status(phase,**kw):write(R/'status.json',dict(phase=phase,time=time.time(),**kw))
def cleanup():
 for p in children:
  try:os.killpg(p.pid,signal.SIGTERM)
  except ProcessLookupError:pass
 deadline=time.monotonic()+35
 while time.monotonic()<deadline and any(p.poll() is None for p in children):time.sleep(.5)
 for p in children:
  if p.poll() is None:
   try:os.killpg(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
 for h in locks:h.close()
def ready(port):
 try:
  with socket.create_connection(('127.0.0.1',port),1):return True
 except OSError:return False

def start_policy(gpu):
 port=20500+gpu;log=(R/f'policy-gpu{gpu}.log').open('xb')
 p=subprocess.Popen(policy_command(port),env=lane_env(gpu,'policy'),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
 children.append(p);write(R/f'policy-gpu{gpu}.identity.json',dict(identity(p.pid),gpu=gpu,port=port))
 start=time.monotonic()
 while not ready(port):
  if stopping or p.poll() is not None or time.monotonic()-start>900:raise RuntimeError(f'policy_start_failed_gpu{gpu}')
  time.sleep(2)
 return p

def main():
 m=json.loads((R/'manifest.json').read_text());registration=hashlib.sha256((R/'manifest.json').read_bytes()).hexdigest()
 assert registration==(R/'registration.sha256').read_text().strip();verify(R,m)
 os.environ.update(PAOS_LIBERO_SOURCE=m['source'],PAOS_CORE_ROOT=m['paos_core'],PAOS_MIGRATION_ROOT=str(B))
 write(R/'controller.identity.json',identity(os.getpid()))
 for gpu in m['gpus']:
  lock=(B/'portable-runtime-20261023/paos/qwen-deploy'/f'gpt-gpu{gpu}-run.lock').open('a')
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
  used=int(subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
  if used>1024:raise RuntimeError(f'gpu{gpu}_occupied_no_work_started')
  if ready(20500+gpu):raise RuntimeError('policy_port_occupied')
 status('starting_policies',gpus=m['gpus'],planned=120)
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:policies=list(pool.map(start_policy,m['gpus']))
 verify(R,m)
 workers=[]
 for gpu in m['gpus']:
  log=(R/f'worker-gpu{gpu}.log').open('xb')
  p=subprocess.Popen([str(B/'conda-envs/paos-agent/bin/python'),str(R/'code/study_worker.py'),'--root',str(R),'--gpu',str(gpu)],env=lane_env(gpu,'agent'),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
  children.append(p);workers.append(p);write(R/f'worker-gpu{gpu}.identity.json',identity(p.pid))
 started=time.monotonic()
 while not stopping:
  if hashlib.sha256((R/'manifest.json').read_bytes()).hexdigest()!=registration:raise RuntimeError('registration_changed')
  if time.monotonic()-started>m['study_timeout_seconds']:raise RuntimeError('study_timeout')
  if (R/'blocked.json').exists():raise RuntimeError('case_infrastructure_blocked')
  if any(p.poll() is not None for p in policies):raise RuntimeError('policy_service_exited')
  if any(p.poll() not in (None,0) for p in workers):raise RuntimeError('worker_exited')
  rows=[]
  for job in m['jobs']:
   f=R/'cases'/job['id']/'result.json'
   if f.exists():
    result=json.loads(f.read_text())
    if result.get('registration_sha256')==registration and result.get('registered_arm')==job['arm']:rows.append(dict(job,result=result))
  for gpu in m['gpus']:
   p=R/f'lane-gpu{gpu}.json'
   if p.exists():
    lane=json.loads(p.read_text())
    if lane['phase']=='running' and time.time()-lane['time']>m['episode_timeout_seconds']:raise RuntimeError('registered_episode_timeout')
  counts={a:sum(x['arm']==a for x in rows) for a in m['arm_policies']}
  status('running',completed=len(rows),planned=120,completed_by_arm=counts,gpus=m['gpus'])
  if all(p.poll() is not None for p in workers):
   if len(rows)!=120:raise RuntimeError('incomplete_registered_study')
   write(R/'completed-results.json',rows);status('completed',completed=120,planned=120);return
  time.sleep(10)
 status('stopped_by_request',completed=None,planned=120)
if __name__=='__main__':
 try:
  with (R/'controller.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
 except BaseException as e:
  status('blocked',reason=str(e)[:200],error_type=type(e).__name__,automatic_retry=False);(R/'STOP').touch();raise
 finally:cleanup()
