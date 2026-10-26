import argparse,fcntl,hashlib,json,os,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--platform',choices=['twin','casa'],required=True);p.add_argument('--gpu',type=int,choices=range(7),required=True);a=p.parse_args()
root=Path('/data/stormlab/xi/robot');code=Path(__file__).resolve().parent;pointer=code/f'latest-{a.platform}.json'
with pointer.with_suffix('.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 if pointer.exists():print(pointer.read_text());raise SystemExit(0)
 out=root/'runs'/('memory-scale-v2_2-'+a.platform+'-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()));out.mkdir()
 files={str(f.relative_to(code)):hashlib.sha256(f.read_bytes()).hexdigest() for f in code.glob('*.py')}
 (out/'code-manifest.json').write_text(json.dumps(files,indent=2))
 e=dict(os.environ,LITELLM_LOCAL_MODEL_COST_MAP='True',PYTHONUNBUFFERED='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
 with (out/'queue.log').open('w') as log:
  q=subprocess.Popen(['/home/xi/envs/agent/bin/python',str(code/'scale_queue.py'),'--platform',a.platform,'--gpu',str(a.gpu),'--output',str(out)],env=e,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 d=dict(pid=q.pid,start_ticks=Path(f'/proc/{q.pid}/stat').read_text().split()[21],output=str(out),gpu=a.gpu,code=str(code),platform=a.platform)
 pointer.write_text(json.dumps(d,indent=2));(out/'launch.json').write_text(json.dumps(d,indent=2));print(json.dumps(d))
