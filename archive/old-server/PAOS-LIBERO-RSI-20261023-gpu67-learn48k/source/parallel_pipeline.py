"""Native/fixed unchanged. RSI r4 fixes bounded optimizer feedback only."""
import argparse,asyncio,hashlib,signal,threading,time,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait
from durable_queue import read
from parallel_runtime import ParallelExperiment,GpuPool
from repair_learning import RepairExperiment,initialize_repair
from physical_runner import PhysicalRunner
from unified_pipeline import ARMS,gateway_contract,matched_summary
from stream_learning import run as learn
from stream_design import SEED_PROCEDURES,compile_procedures
from memory_policy import digest
from replay import dump
from run_queue import identity

def main(out,gpus):
    out=Path(out);stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    dump(out/'coordinator.json',identity(os.getpid()))
    worker_dir=out/('parallel-gpu-workers-'+str(time.time_ns()));worker_dir.mkdir()
    runner=PhysicalRunner(worker_dir,stop,gpus);pool=GpuPool(gpus,stop)
    schedule=read(out/'manifest.json')['schedule']
    try:
        gateway_contract(stop);runner.acquire(lambda status,**kw:dump(out/'progress.json',dict(status=status,**kw,updated_unix=time.time())))
        def lane(arm):
            folder=out/('evolved-r4' if arm=='evolved' else arm)
            if arm=='evolved':
                initialize_repair(out/'evolved/learning',folder/'learning')
                e=RepairExperiment(folder,ARMS[arm],out/'selected-orders.json',out/'budget.json',stop,runner,pool,old_learning=out/'evolved/learning')
            else:
                e=ParallelExperiment(folder,ARMS[arm],out/'selected-orders.json',out/'budget.json',stop,runner,pool)
            fixed=compile_procedures(SEED_PROCEDURES)
            existing=read(folder/'policies/fixed.json')
            if existing is not None and existing!=fixed:raise RuntimeError('fixed_policy_changed')
            dump(folder/'policies/fixed.json',fixed)
            if arm=='evolved':
                learning=asyncio.run(learn(folder/'learning',e,out/'budget.json'))
                selected=read(folder/'learning/frozen-policy.json')
                if digest(selected)!=learning['frozen_sha256']:raise RuntimeError('freeze_changed')
                dump(folder/'policies/evolved.json',selected)
                dump(folder/'freeze.json',dict(seed=digest(fixed),selected=digest(selected),promotions=learning['promotions'],before_first_evolved_heldout=True))
            policies={arm:folder/f'policies/{arm}.json'} if arm!='native' else {}
            rows=e.batch([r for r in schedule if r['arm']==arm],policies,folder/'evaluation')
            dump(folder/'report.json',{'status':'completed','terminal':len(rows)})
            return rows
        for arm in ARMS:
            p=out/('evolved-r4' if arm=='evolved' else arm)/'report.json'
            if p.exists():p.rename(p.with_name('report-before-parallel-'+str(time.time_ns())+'.json'))
        p=out/'report.json'
        if p.exists():p.rename(p.with_name('report-before-parallel-'+str(time.time_ns())+'.json'))
        def isolated_lane(arm):
            try:return lane(arm)
            except Exception as ex:
                if arm!='evolved':raise
                dump(out/'evolved-r4/report.json',{'status':'blocked','error_type':type(ex).__name__,
                     'error_code':str(ex) if type(ex).__name__ in ('StructuredFailure','RuntimeError','ValueError') else 'inspect_structured_audit'})
                return [] # Do not abort unrelated native/fixed work.
        with ThreadPoolExecutor(3) as executor:
            futures={executor.submit(isolated_lane,a):a for a in ARMS};pending=set(futures)
            while pending:
                done,pending=wait(pending,timeout=2)
                dump(out/'progress.json',{'status':'running','gpus':list(gpus),'scheduling_revision':'rsi-repair-r4',
                  'arms':{a:read(out/('evolved-r4' if a=='evolved' else a)/'report.json',{}).get('status','running') for a in ARMS},'updated_unix':time.time()})
                for f in done:
                    if f.exception() is not None:stop.set()
            rows=[]
            for f in futures:rows.extend(f.result())
        dump(out/'paired-summary-r4.json',matched_summary(rows,schedule))
        dump(out/'report.json',{'status':'completed' if len(rows)==len(schedule) else 'partial_failure','terminal':len(rows),'learned_gain_not_assumed':True,'evolved_source':'evolved-r4'})
    except BaseException as ex:
        stop.set();dump(out/'report.json',{'status':'failed','error_type':type(ex).__name__})
        return 2
    finally:runner.close()
    return 0
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--gpus',nargs='+',type=int,required=True);a=p.parse_args()
    if len(set(a.gpus))!=len(a.gpus) or not set(a.gpus)<=set(range(6)):raise SystemExit('GPU allocation invalid')
    raise SystemExit(main(a.output,a.gpus))
