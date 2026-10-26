import pathlib,json,os,signal,time,sys,hashlib,shutil,subprocess
b=pathlib.Path('/data/songziying/paos-libero-20261023');r=pathlib.Path(json.loads((b/'active-study.json').read_text())['root']);state=json.loads((r/'queue-status.json').read_text());pid=state['pid']
assert state['phase']=='running';assert str(r/'code/queue_v2.py').encode() in pathlib.Path(f'/proc/{pid}/cmdline').read_bytes()
os.kill(pid,signal.SIGSTOP)
record={'phase':'waiting_current_case','previous_queue_pid':pid,'job':state['job'],'time':time.time(),'repair_pid':os.getpid()};p=r/'policy-reconnect-repair.json';p.write_text(json.dumps(record,indent=2))
result=pathlib.Path(state['job']['output'])/'result.json'
while not result.exists():time.sleep(10)
cmd=pathlib.Path(f'/proc/{pid}/cmdline')
if cmd.exists() and str(r/'code/queue_v2.py').encode() in cmd.read_bytes():os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
h=r/'runtime-repair-history'/str(time.time_ns());h.mkdir(parents=True)
for name in ('registration.json','registration.sha256','code/runtime/native_world_entry.py','code/queue_v2.py'):
 q=r/name;d=h/name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(q,d)
shutil.copy2(b/'policy-reconnect-incoming/reliable_policy.py',r/'source/reliable_policy.py')
q=r/'code/runtime/native_world_entry.py';s=q.read_text();assert '    install_physics_runtime()' in s;s=s.replace('    install_physics_runtime()','    install_physics_runtime()\n    from reliable_policy import install\n    install()');q.write_text(s)
q=r/'code/queue_v2.py';s=q.read_text().replace("('execution_failure','technical_failure','unclassified_failure')","('execution_failure','technical_failure','unclassified_failure','infrastructure_failure')");q.write_text(s)
m=json.loads((r/'registration.json').read_text());m['administrative_amendments'].append({'time':time.time(),'reason':'Observed policy WebSocket keepalive timeout; lazy connection and identical paired-query transport retry; no physical action before successful response','method_or_budget_changed':False,'old_failed_cases_preserved':True})
for name in ('source/reliable_policy.py','code/runtime/native_world_entry.py','code/queue_v2.py'):m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n');(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
import runtime_adapter
runtime_adapter.configure(7,20517,str(r/'paos-core'))
with (r/'queue-reconnected.log').open('x') as log:
 child=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
record.update(phase='applied_queue_resumed',queue_pid=child.pid,finished=time.time());p.write_text(json.dumps(record,indent=2))
