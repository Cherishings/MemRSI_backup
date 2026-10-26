"""Wait baseline completion, develop20, freeze, paired Mem-before/Mem-after96."""
import argparse,asyncio,os,signal,threading,time
from pathlib import Path
from replay import dump
from run_queue import identity
from durable_queue import DurableExperiment,read
from physical_runner import same_process
from queue012 import COMPARISON
from stream_design import heldout_rows,SEED_PROCEDURES,compile_procedures
from stream_learning import run as learn
from memory_policy import digest
from pipeline_v15 import summarize

def paired_report(rows):
    grouped={}
    for r in rows:grouped.setdefault((r['dataset'],r['condition'],r['repeat']),{})[r['arm']]=r
    counts=dict(both_success=0,improved=0,regressed=0,both_failed=0,technical_unpaired=0)
    invalid={'infrastructure_failure','cancelled'}
    records=[]
    for key,p in grouped.items():
        a,b=p.get('before'),p.get('evolved')
        if not a or not b or a['status'] in invalid or b['status'] in invalid:k='technical_unpaired'
        else:
            sa,sb=a['status']=='success',b['status']=='success'
            k='both_success' if sa and sb else 'improved' if sb else 'regressed' if sa else 'both_failed'
        counts[k]+=1;records.append({'condition':key,'outcome':k})
    return dict(counts=counts,pairs=records,planned_pairs=48,
        note='Protocol/budget failures remain method outcomes. Report all status buckets and checkpoint coverage separately.')

def main(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True);stop=threading.Event();e=None
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    dump(out/'coordinator.json',identity(os.getpid()))
    try:
        prior=read(a.after);src=Path(prior['result'])
        while same_process(prior['coordinator']) or read(src/'report.json',{}).get('status')!='completed':
            dump(out/'progress.json',{'status':'waiting_baseline_completion','baseline':str(src),'updated_unix':time.time()})
            if stop.wait(30):raise RuntimeError('queue_cancelled')
        # Copy only protocol inputs and schedules; never training on baseline outcomes.
        for name in ('selected-orders.json','budget.json'):
            dest=out/name
            if dest.exists() and dest.read_bytes()!=(src/name).read_bytes():raise RuntimeError('input_changed')
            if not dest.exists():dest.write_bytes((src/name).read_bytes())
        comp=read(COMPARISON/'manifest.json')['schedule'];trans=read(src/'manifest.json')['transfer_schedule']
        schedule=heldout_rows(comp,trans)
        manifest={'version':'stream-v1.6','gpus':[0,1,2],'development_physical':20,'heldout_pairs':48,
            'heldout_physical':96,'schedule':schedule,'baseline_source':str(src),
            'gateway':'memory-v3-tool-choice','before_after_same_runtime':True,
            'legacy_fixed_comparison_confounded_by_gateway_repair':True,
            'native_core_and_physical_executor_unchanged':True,'automatic_monitoring_enabled':False}
        old=read(out/'manifest.json')
        if old is not None and old!=manifest:raise RuntimeError('manifest_changed')
        dump(out/'manifest.json',manifest)
        e=DurableExperiment(out,(0,1,2),out/'selected-orders.json',out/'budget.json',stop)
        e.wait_gateway();e.acquire()
        learned=asyncio.run(learn(out/'learning',e,out/'budget.json'))
        before=compile_procedures(SEED_PROCEDURES);after=read(out/'learning/frozen-policy.json')
        if digest(after)!=learned['frozen_sha256']:raise RuntimeError('freeze_changed')
        dump(out/'policies/before.json',before);dump(out/'policies/evolved.json',after)
        dump(out/'freeze.json',dict(before=digest(before),evolved=digest(after),
            accepted_updates=learned['promotions'],frozen_before_any_heldout_trial=True))
        e.state('heldout_physical_evaluation',promotions=learned['promotions'])
        results=e.batch(schedule,{k:out/f'policies/{k}.json' for k in ('before','evolved')},out/'evaluation')
        dump(out/'summary.json',summarize(results,schedule));dump(out/'paired-summary.json',paired_report(results))
        dump(out/'report.json',dict(status='completed',learning=learned,
            heldout_terminal=len(results),paired=paired_report(results),gain_not_automatically_claimed=True))
    except Exception as ex:
        dump(out/'report.json',dict(status='cancelled' if stop.is_set() else 'failed',error_type=type(ex).__name__))
    finally:
        if e:e.close()
    return 0 if read(out/'report.json',{}).get('status')=='completed' else 2
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--after',required=True)
    raise SystemExit(main(p.parse_args()))
