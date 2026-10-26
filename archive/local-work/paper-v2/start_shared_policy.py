import pathlib,subprocess,os,time,json,sys,socket
base=pathlib.Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023-gpu67-learn48k-runtimefix');r=base.with_name('PAOS-LIBERO-shared-JAX-20261023')
r.mkdir(exist_ok=True)
if not (r/'code').exists():(r/'code').symlink_to(base/'code',target_is_directory=True)
processes=[]
for gpu in (6,7):
 status=r/'policy-services'/f'gpu{gpu}'/'status.json'
 if status.exists():raise RuntimeError('Existing service registration; inspect instead of duplicate launch')
 f=(r/f'gpu{gpu}.log').open('x')
 p=subprocess.Popen([sys.executable,str(base/'code/policy_supervisor.py'),'--root',str(r),'--source',str(base/'source'),'--core',str(base/'paos-core'),'--gpu',str(gpu)],stdout=f,stderr=f);processes.append(p)
 start=time.monotonic()
 while time.monotonic()-start<930:
  if p.poll() is not None:raise RuntimeError('policy process failed')
  if status.exists() and json.loads(status.read_text()).get('state')=='ready':break
  time.sleep(3)
 else:raise RuntimeError('startup timeout')
 print(json.dumps({'gpu':gpu,'state':'ready','root':str(r)}),flush=True)
while all(p.poll() is None for p in processes):time.sleep(10)
raise RuntimeError('owned policy supervisor exited')
