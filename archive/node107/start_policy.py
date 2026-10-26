from pathlib import Path
import socket,subprocess,os,re,json,time
b=Path('/data/songziying/paos-libero-20261023')
try:
 with socket.create_connection(('127.0.0.1',20507),2):pass
 print('20507 已有服务；未重复启动。');raise SystemExit(0)
except OSError:pass
s=subprocess.check_output(['/opt/dtk/bin/rocm-smi','--showmeminfo','vram'],text=True)
m=re.search(r'HCU\[7\].*Total Used Memory \(MiB\):\s*(\d+)',s)
if not m or int(m[1])>256:raise SystemExit('7 号卡不空闲或无法确认，未启动。')
log=b/'logs'/('policy-gpu7-'+str(time.time_ns())+'.log')
with log.open('x') as f:
 p=subprocess.Popen([str(b/'migration/conda-envs/paos-policy/bin/python'),str(b/'policy_hcu.py'),'--port','20507','--checkpoint',str(b/'migration/models/pi05_libero')],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
print(json.dumps({'pid':p.pid,'log':str(log),'gpu':7}))
