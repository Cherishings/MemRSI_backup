"""Finite new-hardware G/U replication. Preserve historical results; fail closed."""
import asyncio,hashlib,importlib.util,json,os,signal,subprocess,sys,time
from pathlib import Path
B=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022');P=B/'portable-runtime-20261023'
ROOT=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-validation-20261023')
HERE=Path(__file__).resolve().parent;OUT=ROOT/'gu-factorial';PY=B/'conda-envs/paos-agent/bin/python'
sys.path[:0]=[str(B/'PhyAgentOS-core'),str(HERE)]
from base_interventions import ARMS,policy_for,digest
spec=importlib.util.spec_from_file_location('cap',P/'robot/paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
children=[];stop=False

def stopped(*_):
 global stop
 stop=True
 for child in children:
  if child.poll() is None: child.terminate()
for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stopped)
def status(phase,**kw):cap.write(ROOT/'status.json',dict(phase=phase,time=time.time(),**kw))
def prepare():
 original=B/'robot/runs/paper-completion-20261020/gu-repair-r2-20261022'
 m=cap.read(original/'manifest.json');parent=cap.read(original/'frozen-policy.json')
 source=P/'robot/memory-scale-v2_2';core=P/'paos/worktrees/memrsi-bounded-v2_2'
 jobs=m['jobs'];assert len(jobs)==192 and {j['arm'] for j in jobs}==set(ARMS)
 for j in jobs:assert j['plan']['platform']=='casa'
 record=dict(source=str(source),core=str(core),source_identity=cap.source_identity(source,core),jobs=jobs,arms=ARMS,budget=m['budget'],policy_sha256=digest(parent),effective_policy_sha256={a:digest(policy_for(parent,a)) for a in ARMS},code_sha256={p.name:cap.file_sha(p) for p in HERE.glob('*.py')},replicate_block='newserver-gu-factorial-20261023',start_before_epoch=time.time()+48*3600,registered_at=time.time(),gpus=[2,3],available_gpu_checks=[2,3,4,6,7],forbidden_occupied_gpus=[0,1,5],historical_manifest_sha256=cap.file_sha(original/'manifest.json'),scope='New-hardware diagnostic replication on 48 previously viewed conditions. Not unseen generalization, not RSI. No pooling with old-hardware results.',learning_calls=0,per_case_logical_model_call_cap=480,max_attempts_per_case=1,first_four_gate='Actual model request, guidance injection, and native/custom archival traces; no success-rate threshold.',primary_comparison='g1_u1 versus g0_u1 paired complete-workflow success',secondary_comparisons=['g1_u1 versus g1_u0','g1_u1 versus g0_u0','all G/U effects, failures, calls and tokens'],stop_rule='Any technical failure, unclassified exception, or information-flow gate failure blocks new dispatch. Preserve all observations.',downstream='After complete development audit, preregister disjoint validation/heldout manifests and a separate bounded RSI learning allocation. No automatic reuse of test feedback.')
 if (OUT/'manifest.json').exists():raise RuntimeError('existing_registration_refuse_overwrite')
 OUT.mkdir(parents=True);cap.write(OUT/'manifest.json',record);cap.write(OUT/'frozen-policy.json',parent)
 cap.write(ROOT/'registration.json',{'planned':192,'first_gate_trials':4,'workers':2,'model':'gpt-5.6-luna','gpus':[2,3],'phase4_RSI':'not started; requires independent split and freeze after development audit','phase5_generalization':'not started; asset and task acceptance required','scope':record['scope']})
 return record

def native_acceptance(m):
 # The exact experiment backend must execute successfully before model dispatch.
 sys.path.insert(0,m['core']);engine=cap.load_engine(m['source'],m['core'])
 used=lambda:int(subprocess.check_output(['nvidia-smi','-i','2','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
 with engine.acquire(engine.LEASES/engine.lock_name(2),True,used):
  sim=engine.Physical('casa',2,ROOT/'casa-exact-backend')
  try:
   ready=sim.ready();assert ready['status']=='ready'
   result=sim.call('station_A');cap.write(ROOT/'casa-physical-acceptance.json',result)
   if not result.get('success') or not result.get('native_task_complete'):raise RuntimeError('casa_exact_physical_acceptance_failed')
  finally:sim.close()

def main():
 with cap.locked(ROOT/'coordinator.lock',nonblocking=True):
  m=prepare();cap.write(ROOT/'coordinator.json',cap.identity())
  deadline=m['start_before_epoch']
  while not stop:
   if time.time()>deadline:raise RuntimeError('asset_or_mechanism_wait_deadline')
   probe=cap.read(ROOT/'live-gu-probe/result.json',{})
   if probe.get('phase')=='blocked':raise RuntimeError('live_mechanism_probe_blocked')
   installed=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/casa-assets.tar.zst.installed').exists()
   if installed and probe.get('phase')=='passed':break
   status('waiting_prerequisites',casa_assets_installed=installed,live_mechanism=probe.get('phase','running'),planned_trials=192)
   time.sleep(15)
  if stop:return
  status('physical_backend_acceptance');native_acceptance(m)
  if stop:return
  env=dict(os.environ,PYTHONPATH=str(B/'PhyAgentOS-core'),LITELLM_LOCAL_MODEL_COST_MAP='True',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
  for gpu in (2,3):
   log=(OUT/f'worker-gpu{gpu}.log').open('ab')
   proc=subprocess.Popen([str(PY),str(HERE/'worker.py'),'--gpu',str(gpu),'--output',str(OUT)],env=env,stdout=log,stderr=log,stdin=subprocess.DEVNULL)
   children.append(proc)
  cap.write(ROOT/'workers.json',{str(g):cap.identity(p.pid) for g,p in zip((2,3),children)})
  while not stop:
   done=[j for j in m['jobs'] if (OUT/j['key']/'result.json').exists()]
   gate=cap.read(OUT/'contract-gate.json',{})
   blocked=cap.read(OUT/'blocked.json')
   if blocked:raise RuntimeError('registered_worker_blocked')
   if any(p.poll() not in (None,0) for p in children):raise RuntimeError('worker_exited_abnormally')
   status('running',completed=len(done),planned=192,gate=gate.get('state'),worker_pids=[p.pid for p in children])
   if all(p.poll() is not None for p in children):
    if len(done)!=192:raise RuntimeError('incomplete_queue')
    rows=[dict(key=j['key'],arm=j['arm'],condition=j['condition_id'],result=cap.read(OUT/j['key']/'result.json')) for j in m['jobs']]
    cap.write(ROOT/'completed-results.json',rows);status('completed',completed=192,planned=192,scope=m['scope']);return
   time.sleep(15)
try:main()
except BaseException as e:
 status('blocked',reason=str(e)[:150],error_type=type(e).__name__,automatic_retry=False)
 stopped()
 for p in children:
  try:p.wait(timeout=45)
  except subprocess.TimeoutExpired:p.kill()
 raise
