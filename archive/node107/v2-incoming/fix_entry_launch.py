import pathlib,json,shutil,hashlib,time,subprocess,sys
b=pathlib.Path('/data/songziying/paos-libero-20261023');r=b/'study-scope-v2';state=json.loads((r/'queue-status.json').read_text());assert state['phase']=='blocked';assert not pathlib.Path(state['job']['output']).exists()
h=r/'technical-history'/str(time.time_ns());h.mkdir(parents=True)
for name in ('queue.log','queue-status.json','queue-launch.json','registration.json','registration.sha256','code/case_v2.py'):
 p=r/name;d=h/name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
for p in (r/'logs').glob('*.log'):shutil.move(str(p),h/p.name)
shutil.copy2(b/'v2-incoming/case_v2.py',r/'code/case_v2.py')
m=json.loads((r/'registration.json').read_text());m['frozen_files']['code/case_v2.py']=hashlib.sha256((r/'code/case_v2.py').read_bytes()).hexdigest();m['administrative_amendments'].append({'reason':'Missing protocol import path fixed before any model or physics execution','time':time.time()});(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n');(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
import planning,runtime_adapter
runtime_adapter.configure(7,20517,str(r/'paos-core'))
import feedback_workflow,twenty_agent,twenty_protocol,method,model_provider
with (r/'queue.log').open('w') as f:p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdout=f,stderr=f,stdin=subprocess.DEVNULL,start_new_session=True)
(r/'queue-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}));print(p.pid)
