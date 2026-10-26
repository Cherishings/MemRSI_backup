import pathlib,json,os,signal,time,hashlib,subprocess,sys
r=pathlib.Path('/data/songziying/paos-libero-20261023/study-rsi-v4-sources');q=json.loads((r/'queue-status.json').read_text());pid=q['pid'];assert q['phase']=='waiting_for_verified_JAX_policy';assert not list((r/'development').glob('*/*/result.json'));assert pathlib.Path(f'/proc/{pid}/task/{pid}/children').read_text().strip()==''
os.kill(pid,signal.SIGSTOP)
p=r/'code/queue_v2.py';s=p.read_text();assert 'metadata=client.get_server_metadata();client._ws.close();break' in s
backup=r/'preflight-repair-history';backup.mkdir()
for name in ['registration.json','registration.sha256']:(backup/name).write_bytes((r/name).read_bytes())
(backup/'queue_v2.py').write_text(s)
# Metadata handshake is the readiness criterion; closing an idle probe must not veto it.
s=s.replace('metadata=client.get_server_metadata();client._ws.close();break','metadata=client.get_server_metadata()\n  try:client._ws.close()\n  except TimeoutError:pass\n  break')
compile(s,str(p),'exec');p.write_text(s)
m=json.loads((r/'registration.json').read_text());m['frozen_files']['code/queue_v2.py']=hashlib.sha256(p.read_bytes()).hexdigest();m['administrative_amendments'].append({'time':time.time(),'reason':'Preflight close timeout must not invalidate successful metadata handshake; no case started','method_or_budget_changed':False});(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n');(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
for _ in range(50):
 if not pathlib.Path(f'/proc/{pid}').exists():break
 time.sleep(.1)
with (r/'queue-preflight-fixed.log').open('x') as log:p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
(r/'queue-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}));print(p.pid)
