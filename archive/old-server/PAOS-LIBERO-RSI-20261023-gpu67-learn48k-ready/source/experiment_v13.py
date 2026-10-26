"""One owner for three GPU leases; bounded trials, no capability/infra reruns."""
import concurrent.futures
import json
import subprocess
import threading
import time
from pathlib import Path
from run_queue import ROOT, env
from network_wait import paused_seconds
from replay import dump
from physical_runner import PhysicalRunner, PORTS, AGENT_PYTHON

TECH = {'infrastructure_failure','protocol_failure','budget_failure','guidance_failure','cancelled'}

class Experiment:
    def __init__(self, output, gpus, orders, budget, stop, timeout=10800):
        self.out=Path(output);self.out.mkdir(parents=True,exist_ok=True)
        self.gpus=tuple(gpus);self.orders=Path(orders);self.budget=Path(budget)
        self.stop=stop;self.timeout=timeout;self.lock=threading.RLock();self.active={}
        workers=self.out/'gpu-workers';workers.mkdir()
        self.runner=PhysicalRunner(workers,stop,gpus=self.gpus)
        self.frozen={p.name:p.read_bytes() for p in ROOT.glob('*.py')}
    def state(self,status='running',**fields):
        with self.lock:dump(self.out/'progress.json',dict(status=status,active=dict(self.active),updated_unix=time.time(),**fields))
    def acquire(self):self.runner.acquire(self.state)
    def episode(self,row,policy,dest):
        if any((ROOT/n).read_bytes()!=v for n,v in self.frozen.items()):raise RuntimeError('source_changed')
        dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():raise RuntimeError('episode_output_already_exists')
        gpu=row['gpu'];cmd=[AGENT_PYTHON,str(ROOT/'feedback_workflow.py'),'--output',str(dest),
            '--orders',str(self.orders),'--budget',str(self.budget),'--port',str(PORTS[gpu]),
            '--init',str(row['init']),'--variant','0','--history',row['history'],
            '--arm','native' if row['arm']=='native' else 'memrsi']
        if row['arm']!='native':cmd+=['--memory-policy',str(policy)]
        with dest.with_suffix('.log').open('xb') as log:
            child=subprocess.Popen(cmd,cwd=ROOT,env=env(gpu),stdin=subprocess.DEVNULL,
                stdout=log,stderr=log,start_new_session=True)
        record=self.runner.track(child,'worker')
        with self.lock:self.active[str(gpu)]=dict(row,worker=record,output=str(dest));self.state()
        error=None;started=time.monotonic()
        try:
            while child.poll() is None:
                if self.stop.wait(2):error='cancelled';break
                if time.monotonic()-started-paused_seconds(dest)>self.timeout:error='worker_timeout';break
            if error:self.runner.stop_owned(child)
            p=dest/'result.json';result=json.loads(p.read_text()) if p.exists() else {'status':'infrastructure_failure','error_code':'worker_exit'}
            if error:result.update(status='cancelled' if error=='cancelled' else 'infrastructure_failure',error_code=error)
            return dict(result,**row,output=str(dest),worker=record,transport_revision='network-wait-v4',network_wait_seconds=paused_seconds(dest))
        finally:
            if child.poll() is None:self.runner.stop_owned(child)
            self.runner.release_process(child)
            with self.lock:self.active.pop(str(gpu),None);self.state()
    def batch(self,rows,policies,output,strict_technical=False):
        output=Path(output);output.mkdir(parents=True,exist_ok=False);results=[];errors=[]
        dump(output/'schedule.json',rows)
        def lane(gpu):
            bad=0
            for row in (r for r in rows if r['gpu']==gpu):
                if self.stop.is_set():return
                result=self.episode(row,policies.get(row['arm']),output/row['trial_id'])
                with self.lock:
                    results.append(result);dump(output/'rows.json',results)
                bad=bad+1 if result['status'] in TECH else 0
                if (strict_technical and bad) or bad>=2:
                    errors.append('technical_hold');self.stop.set();return
        with concurrent.futures.ThreadPoolExecutor(len(self.gpus)) as pool:
            futures=[pool.submit(lane,g) for g in self.gpus]
            for f in concurrent.futures.as_completed(futures):
                try:f.result()
                except BaseException:self.stop.set();raise
        dump(output/'completion.json',{'planned':len(rows),'terminal':len(results),
            'status':'completed' if len(results)==len(rows) and not errors else 'technical_hold' if errors else 'interrupted'})
        if errors:raise RuntimeError('technical_hold')
        if len(results)!=len(rows):raise RuntimeError('queue_cancelled')
        return results
    def close(self):self.runner.close()
