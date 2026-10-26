"""Execute three unstarted canonical trials on the newly free GPUs during drain."""
import json,os,signal,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from durable_queue import read
from experiment_v13 import Experiment
from physical_runner import PhysicalRunner
from stream_design import development_rows
from replay import dump
from run_queue import BASE,identity
OUT=BASE/'results/memrsi-stream-v1_6r1-20261012T060413Z/experiment'
def main():
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    folder=OUT/'parallel-prefill';folder.mkdir(exist_ok=True)
    dump(folder/'coordinator.json',identity(os.getpid()))
    jobs=[]
    active={w['trial_id'] for w in read(OUT/'parallel-drain.json')['active']}
    for arm,gpu in [('native',3),('fixed',4)]:
        schedule=read(OUT/'manifest.json')['schedule']
        rows=[r for r in schedule if r['arm']==arm and r['trial_id'] not in active
              and not list((OUT/arm/'evaluation'/r['trial_id']).glob('attempt-*.launch.json'))]
        row=rows[0];dest=OUT/arm/'evaluation'/row['trial_id']/'attempt-01'
        policy=None if arm=='native' else OUT/arm/'policies/fixed.json'
        jobs.append((row,gpu,dest,policy))
    # Current second batch uses the already frozen round-1 parent for ALL five episodes.
    row=dict(development_rows()[6],gpu=2)
    assert row['trial_id']=='dev-06' and row['trial_id'] not in active
    dest=OUT/'evolved/learning/round-1/physical'/row['trial_id']/'attempt-01'
    assert not dest.with_suffix('.launch.json').exists()
    jobs.append((row,5,dest,OUT/'evolved/learning/round-1/parent-policy.json'))
    for row,gpu,dest,policy in jobs:
        assert not dest.exists() and not dest.with_suffix('.launch.json').exists()
        if policy is not None:assert policy.exists()
    dump(folder/'allocation.json',[dict(row,execution_gpu=gpu,output=str(dest),policy=str(policy) if policy else None) for row,gpu,dest,policy in jobs])
    e=Experiment(folder,(3,4,5),OUT/'selected-orders.json',OUT/'budget.json',stop)
    try:
        e.acquire()
        def task(job):
            row,gpu,dest,policy=job
            dump(dest.with_suffix('.launch.json'),dict(row,output=str(dest),attempt=1,execution_gpu=gpu))
            result=e.episode(dict(row,gpu=gpu),policy,dest)
            result.update(row);result.update(execution_gpu=gpu,attempt=1,inherited=False,scheduling_revision='six-gpu-prefill')
            dump(folder/f'result-gpu{gpu}.json',result)
            return result
        with ThreadPoolExecutor(3) as pool:results=list(pool.map(task,jobs))
        dump(folder/'report.json',{'status':'completed','terminal':len(results)})
    finally:e.close()
if __name__=='__main__':main()
