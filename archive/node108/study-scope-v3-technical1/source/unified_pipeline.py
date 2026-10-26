"""Common-runtime three-arm study; old-runtime results are never imported as outcomes."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor, wait
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import time
import urllib.request

from durable_queue import DurableExperiment, read
from memory_policy import digest
from model_provider import GATEWAY_URL, MODEL
from physical_runner import same_process
from pipeline_v15 import summarize
from queue012 import COMPARISON
from replay import dump
from run_queue import identity
from stream_design import heldout_rows, SEED_PROCEDURES, compile_procedures
from stream_learning import run as learn

ARMS = {'native': 0, 'fixed': 1, 'evolved': 2}
GATEWAY_VERSION = 'memory-v3-tool-choice'

def gateway_contract(stop=None, progress=None):
    while True:
        if stop is not None and stop.is_set():raise RuntimeError('queue_cancelled')
        try:
            with urllib.request.urlopen(GATEWAY_URL.removesuffix('/v1')+'/health', timeout=15) as f:
                health = json.load(f)
            break
        except (OSError,ValueError):
            if progress:progress()
            if stop is None:raise
            stop.wait(10)
    if health.get('model') != MODEL or health.get('gateway_version') != GATEWAY_VERSION:
        raise RuntimeError('common_gateway_mismatch')
    return {k: health.get(k) for k in ('model', 'gateway_version', 'transport_revision', 'max_output_tokens')}

def schedule_for_all(comparison, transfer):
    before = [r for r in heldout_rows(comparison, transfer) if r['arm']=='before']
    return [dict(r, arm=arm, gpu=gpu,
                 trial_id=f"{r['dataset']}/{r['condition']}-r{r['repeat']}/{arm}")
            for r in before for arm, gpu in ARMS.items()]

def matched_summary(rows, schedule):
    grouped = {}
    for row in rows:
        key=(row['dataset'],row['condition'],row['repeat'])
        grouped.setdefault(key,{})[row['arm']]=row
    comparisons={}
    for left,right in (('native','fixed'),('native','evolved'),('fixed','evolved')):
        counts=dict(paired=0,left_success=0,right_success=0,improved=0,regressed=0,both_failed=0,both_success=0)
        for group in grouped.values():
            if not all(a in group and group[a]['status'] not in ('infrastructure_failure','cancelled') for a in (left,right)):
                continue
            a,b=(group[x]['status']=='success' for x in (left,right))
            counts['paired']+=1;counts['left_success']+=int(a);counts['right_success']+=int(b)
            counts['both_success' if a and b else 'improved' if b else 'regressed' if a else 'both_failed']+=1
        comparisons[left+'_vs_'+right]=counts
    return {'planned_conditions':len(schedule)//3,'terminal':len(rows),'comparisons':comparisons,
            'all_statuses_and_checkpoint_coverage':summarize(rows,schedule),
            'old_gateway_results_pooled':False,'repeats_are_not_independent_task_families':True}

def lane(arm, out, schedule, stops, orders, budget):
    gpu=ARMS[arm];stop=stops[arm];folder=out/arm;e=None
    try:
        gateway_contract(stop)
        e=DurableExperiment(folder,(gpu,),orders,budget,stop)
        e.wait_gateway();e.acquire()
        fixed=compile_procedures(SEED_PROCEDURES)
        dump(folder/'policies/fixed.json',fixed)
        if arm=='evolved':
            learning=asyncio.run(learn(folder/'learning',e,budget))
            selected=read(folder/'learning/frozen-policy.json')
            if digest(selected)!=learning['frozen_sha256']:raise RuntimeError('freeze_changed')
            dump(folder/'policies/evolved.json',selected)
            dump(folder/'freeze.json',dict(seed=digest(fixed),selected=digest(selected),
                promotions=learning['promotions'],before_first_evolved_heldout=True))
        policies={arm:folder/f'policies/{arm}.json'} if arm!='native' else {}
        rows=e.batch([r for r in schedule if r['arm']==arm],policies,folder/'evaluation')
        dump(folder/'report.json',{'status':'completed','terminal':len(rows)})
        return rows
    except BaseException as ex:
        dump(folder/'report.json',{'status':'cancelled' if stop.is_set() else 'failed','error_type':type(ex).__name__})
        for event in stops.values():event.set()
        raise
    finally:
        if e:e.close()

def main(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    stops={arm:threading.Event() for arm in ARMS}
    def stop_all(*args):
        for event in stops.values():event.set()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop_all)
    dump(out/'coordinator.json',identity(os.getpid()))
    try:
        prior=read(a.after);src=Path(prior['result'])
        if same_process(prior['coordinator']):raise RuntimeError('predecessor_still_alive')
        for name in ('selected-orders.json','budget.json'):
            dest=out/name
            if dest.exists() and dest.read_bytes()!=(src/name).read_bytes():raise RuntimeError('input_changed')
            if not dest.exists():dest.write_bytes((src/name).read_bytes())
        schedule=schedule_for_all(read(COMPARISON/'manifest.json')['schedule'],read(src/'manifest.json')['transfer_schedule'])
        health=gateway_contract(stops['native'],lambda:dump(out/'progress.json',{'status':'waiting_gateway_no_trial_started','updated_unix':time.time()}))
        manifest={'version':'stream-v1.6r1-common-interface','gpus':ARMS,'schedule':schedule,
            'development':20,'heldout':144,'common_gateway':health,'gateway_url':GATEWAY_URL,
            'inputs_sha256':{n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in ('selected-orders.json','budget.json')},
            'supersedes_runtime_only':str(src),'old_results_preserved_not_imported':True,
            'new_protocol_not_retry_of_old_capability_failure':True,
            'seed_is_fixed_before_evolution':True,'learning_reads_baseline_outcomes':False,
            'automated_monitor':False}
        old=read(out/'manifest.json')
        if old is not None and old!=manifest:
            for key in set(old)|set(manifest):
                if key not in ('gateway_url','common_gateway') and old.get(key)!=manifest.get(key):
                    raise RuntimeError('manifest_changed:'+key)
            if not (out/'transport-migration-v4.json').exists():raise RuntimeError('transport_migration_not_audited')
            dump(out/'manifest-transport-v4.json',manifest)
        elif old is None:dump(out/'manifest.json',manifest)
        # Preserve previous coordinator status reports, but stale cancellation
        # reports must not label resumed lanes as already stopped.
        for arm in ARMS:
            report=out/arm/'report.json'
            if report.exists():report.rename(report.with_name('report-before-resume-'+str(time.time_ns())+'.json'))
        report=out/'report.json'
        if report.exists():report.rename(report.with_name('report-before-resume-'+str(time.time_ns())+'.json'))
        with ThreadPoolExecutor(3) as pool:
            futures={pool.submit(lane,arm,out,schedule,stops,out/'selected-orders.json',out/'budget.json'):arm for arm in ARMS}
            pending=set(futures)
            while pending:
                done,pending=wait(pending,timeout=2)
                # Only structured summaries are read here; never passed into the learner.
                status={arm:read(out/arm/'report.json',{}).get('status','running') for arm in ARMS}
                dump(out/'progress.json',{'status':'running','arms':status,'updated_unix':time.time()})
                for f in done:
                    if f.exception() is not None:stop_all()
            rows=[]
            for f in futures:rows.extend(f.result())
        dump(out/'paired-summary.json',matched_summary(rows,schedule))
        dump(out/'report.json',{'status':'completed','terminal':len(rows),'learned_gain_not_assumed':True})
    except BaseException as ex:
        stop_all()
        dump(out/'report.json',{'status':'failed' if not isinstance(ex,KeyboardInterrupt) else 'cancelled','error_type':type(ex).__name__})
        return 2
    return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--after',required=True)
    raise SystemExit(main(p.parse_args()))
