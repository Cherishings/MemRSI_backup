"""Scheduling-only shared GPU pool; canonical trials and attempt budgets unchanged."""
import contextlib
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from durable_queue import DurableExperiment, read, retry, unique_attempts
from experiment_v13 import Experiment
from physical_runner import same_process
from replay import dump

class GpuPool:
    def __init__(self,gpus,stop):
        self.free=list(gpus);self.stop=stop;self.cv=threading.Condition();self.waiters=[]
        self.busy={};self.ready_at=time.monotonic()+.25
    @contextlib.contextmanager
    def lease(self,arm):
        ticket=object()
        with self.cv:
            self.waiters.append((ticket,arm))
            while True:
                if self.stop.is_set():
                    self.waiters=[w for w in self.waiters if w[0] is not ticket]
                    self.cv.notify_all();raise RuntimeError('queue_cancelled')
                first=min(self.waiters,key=lambda w:self.busy.get(w[1],0))
                if self.free and first[0] is ticket and time.monotonic()>=self.ready_at:
                    self.waiters.remove((ticket,arm));gpu=self.free.pop(0)
                    self.busy[arm]=self.busy.get(arm,0)+1;self.cv.notify_all();break
                self.cv.wait(.2)
        try:yield gpu
        finally:
            with self.cv:
                self.free.append(gpu);self.busy[arm]-=1;self.cv.notify_all()

class ParallelExperiment(DurableExperiment):
    def __init__(self,output,logical_gpu,orders,budget,stop,runner,pool):
        # Do not call the old constructor: the shared runner owns all six leases.
        self.out=Path(output);self.out.mkdir(parents=True,exist_ok=True)
        self.gpus=(logical_gpu,) # Preserve the original development manifest.
        self.orders=Path(orders);self.budget=Path(budget);self.stop=stop
        self.timeout=10800;self.lock=threading.RLock();self.active={}
        self.runner=runner;self.pool=pool;self.health_url='http://127.0.0.1:19099/health'
        from run_queue import ROOT
        self.frozen={p.name:p.read_bytes() for p in ROOT.glob('*.py')}
    def close(self):pass # Shared runner closed once by coordinator.
    def batch(self,rows,policies,output,strict_technical=False,inherited=()):
        out=Path(output);out.mkdir(parents=True,exist_ok=True)
        previous=read(out/'schedule.json')
        if previous is not None and previous!=rows:raise RuntimeError('schedule_changed')
        dump(out/'schedule.json',rows)
        attempts=unique_attempts(list(inherited)+read(out/'attempts.json',[]))
        ids={r['trial_id'] for r in rows};attempts=[r for r in attempts if r['trial_id'] in ids]
        for row in rows:
            for launch in sorted((out/row['trial_id']).glob('attempt-*.launch.json')):
                ticket=read(launch);dest=Path(ticket['output'])
                if any(r['output']==str(dest) for r in attempts):continue
                worker=read(dest/'worker-identity.json')
                if worker and same_process(worker):raise RuntimeError('episode_still_alive')
                result=read(dest/'result.json',{'status':'infrastructure_failure','error_code':'interrupted_attempt'})
                attempts.append(dict(result,**row,output=str(dest),attempt=ticket['attempt'],inherited=False,
                                     execution_gpu=ticket.get('execution_gpu',row['gpu'])))
        dump(out/'attempts.json',attempts);selected={}
        def task(row):
            with self.lock:prior=sorted((r for r in attempts if r['trial_id']==row['trial_id']),key=lambda r:r['attempt'])
            last=prior[-1] if prior else None
            # max attempt index, not list length: holes never reset a budget.
            used=max((r['attempt'] for r in prior),default=0)
            if last is None or retry(last):
                for n in range(used+1,4):
                    if self.stop.is_set():return
                    self.wait_gateway()
                    with self.pool.lease(row['arm']) as gpu:
                        if self.stop.is_set():return
                        dest=out/row['trial_id']/f'attempt-{n:02d}'
                        if dest.exists() or dest.with_suffix('.launch.json').exists():raise RuntimeError('duplicate_attempt')
                        dump(dest.with_suffix('.launch.json'),dict(row,output=str(dest),attempt=n,execution_gpu=gpu))
                        actual=dict(row,gpu=gpu)
                        last=self.episode(actual,policies.get(row['arm']),dest)
                        last.update(row);last.update(attempt=n,inherited=False,execution_gpu=gpu,
                                                   scheduling_revision='six-gpu-v1')
                        with self.lock:attempts.append(last);dump(out/'attempts.json',attempts)
                    if not retry(last):break
                    if self.stop.wait(15):return
            if last is not None:
                with self.lock:
                    selected[row['trial_id']]=last
                    dump(out/'rows.json',[selected[r['trial_id']] for r in rows if r['trial_id'] in selected])
        # Shared fair pool balances active arms and lends idle capacity during replay.
        with ThreadPoolExecutor(6) as executor:
            futures=[executor.submit(task,r) for r in rows]
            for future in futures:future.result()
        result=[selected[r['trial_id']] for r in rows if r['trial_id'] in selected]
        dump(out/'completion.json',{'planned':len(rows),'terminal':len(result),'all_attempts':len(attempts),
             'status':'completed' if len(result)==len(rows) else 'interrupted','max_attempts':3,'capability_reruns':0})
        if len(result)!=len(rows):raise RuntimeError('queue_cancelled')
        return result
