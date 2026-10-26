import json,pathlib,time,os,signal,sys,subprocess
r=pathlib.Path(sys.argv[1]);h=json.loads((r/'handoff.json').read_text());old=pathlib.Path(h['previous_root']);result=pathlib.Path(h['previous_job']['output'])/'result.json'
while not result.exists():time.sleep(15)
pid=h['previous_queue_pid'];cmd=pathlib.Path(f'/proc/{pid}/cmdline')
if cmd.exists() and str(old/'code/queue_v2.py').encode() in cmd.read_bytes():
 os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
import runtime_adapter
runtime_adapter.configure(7,20517,str(r/'paos-core'))
import model_provider
assert model_provider.OUTPUT_CAP==8192
with (r/'queue.log').open('x') as log:p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=os.environ.copy())
(r/'queue-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}))
(r.parent/'active-study.json').write_text(json.dumps({'root':str(r),'time':time.time()}))
h.update(phase='launched',queue_pid=p.pid,finished=time.time());(r/'handoff.json').write_text(json.dumps(h,indent=2))
s=json.loads((old/'queue-status.json').read_text());s.update(phase='superseded_after_current_case',next_root=str(r),time=time.time());(old/'queue-status.json').write_text(json.dumps(s,indent=2))
