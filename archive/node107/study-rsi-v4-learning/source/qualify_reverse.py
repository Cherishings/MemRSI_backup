import argparse,concurrent.futures,hashlib,json,signal,subprocess,threading,time
from pathlib import Path
from physical_runner import PhysicalRunner,PORTS,AGENT_PYTHON
from run_queue import ROOT,env,dump,identity

def main(a):
 out=Path(a.output);out.mkdir(exist_ok=False);stop=threading.Event();runner=PhysicalRunner(out,stop)
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
 dump(out/'coordinator.json',identity(__import__('os').getpid()))
 dump(out/'source.json',{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['twenty_protocol.py','twenty_workflow.py','native_world.py','world_client.py','qualify_reverse.py','physical_runner.py']})
 def status(phase,**kw):dump(out/'progress.json',dict(status=phase,time_unix=time.time(),**kw))
 def run(gpu):
  dest=out/f'init{gpu-6}';cmd=[AGENT_PYTHON,str(ROOT/'twenty_workflow.py'),'--output',str(dest),'--orders',a.orders,'--port',str(PORTS[gpu]),'--init',str(gpu-6),'--history','beta' if gpu==6 else 'alpha','--arm','reference']
  with (out/f'gpu{gpu}.log').open('xb') as log:p=subprocess.Popen(cmd,cwd=ROOT,env=env(gpu),stdout=log,stderr=log,start_new_session=True,stdin=subprocess.DEVNULL)
  ident=runner.track(p,'worker');dump(out/f'worker-{gpu}.json',ident)
  start=time.time()
  while p.poll() is None:
   if stop.wait(2) or time.time()-start>5400:runner.stop_owned(p);break
  runner.release_process(p)
  path=dest/'result.json';return json.loads(path.read_text()) if path.exists() else {'status':'infrastructure_failure','gpu':gpu,'returncode':p.poll()}
 try:
  runner.acquire(status);status('physical_reference_running')
  with concurrent.futures.ThreadPoolExecutor(2) as pool:rows=list(pool.map(run,(6,7)))
  dump(out/'report.json',{'status':'completed','qualification_passed':all(r['status']=='success' and r['partial_successes']==5 and r['recovery_successes']==5 for r in rows),'scope':'physical scripted reference only, no memory or model success claim','rows':rows});status('completed')
 finally:runner.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--orders',required=True);main(p.parse_args())
