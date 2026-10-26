import json,subprocess,sys,time,os,socket,fcntl
from pathlib import Path
r=Path(sys.argv[1]);lock=(r/'queue.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def write(d):
 p=r/'queue-status.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(dict(time=time.time(),pid=os.getpid(),**d),indent=2));t.replace(p)
write({'phase':'waiting_for_verified_JAX_policy'})
while True:
 try:
  with socket.create_connection(('127.0.0.1',20517),timeout=3):pass
  # A reverse listener alone is insufficient: require a real websocket handshake.
  from openpi_client.websocket_client_policy import WebsocketClientPolicy
  client=WebsocketClientPolicy('127.0.0.1',20517);metadata=client.get_server_metadata();break
 except (OSError,Exception) as e:
  write({'phase':'waiting_for_verified_JAX_policy','error_type':type(e).__name__});time.sleep(15)
rows=[]
for j in json.loads((r/'development-schedule.json').read_text()):
 out=Path(j['output']);f=out/'result.json'
 if f.exists():rows.append(json.loads(f.read_text()));continue
 if out.exists():write({'phase':'blocked','reason':'interrupted_case_preserved','job':j});sys.exit(2)
 job=r/'jobs'/f"{j['condition_id']}-{j['arm']}.json";job.write_text(json.dumps(j))
 write({'phase':'running','job':j,'completed':len(rows),'policy_metadata':metadata})
 with (r/'logs'/f"{j['condition_id']}-{j['arm']}.log").open('x') as log:
  code=subprocess.call([sys.executable,str(r/'code/case_v2.py'),'--root',str(r),'--job',str(job)],stdout=log,stderr=log)
 if code or not f.exists():write({'phase':'blocked','reason':'worker_failed','exit_code':code,'job':j});sys.exit(2)
 result=json.loads(f.read_text());rows.append(result);(r/'development-rows.json').write_text(json.dumps(rows,indent=2))
 if result['status'] in ('execution_failure','technical_failure','unclassified_failure'):
  write({'phase':'blocked','reason':result['status'],'job':j,'completed':len(rows)});sys.exit(2)
write({'phase':'development_complete','completed':len(rows),'final_test_started':False,'automatic_method_changes':False})
