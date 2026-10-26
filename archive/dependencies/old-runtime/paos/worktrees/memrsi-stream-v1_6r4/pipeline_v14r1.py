"""Fresh v1.4 pipeline. No automatic relaunch/reset; start only via start_v14.py."""
import argparse
import asyncio
import json
import os
import signal
import threading
from pathlib import Path
from replay import dump
from run_queue import ROOT,BASE,identity
from twenty_queue import qualification,PHYSICAL_FILES,sha
from feedback_protocol import schedule,histories,old_histories,DEVELOPMENT_HISTORIES
from memory_policy import BASE as SEED,digest
from experiment_recovery import Experiment
from learning_v14 import prepare,run as learn
from feedback_queue import summarize,paired

def main(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    stop=threading.Event();experiment=None;report={'status':'failed'}
    for s in (signal.SIGTERM,signal.SIGINT):signal.signal(s,lambda *_:stop.set())
    dump(out/'coordinator.json',identity(os.getpid()))
    try:
        qualification(a.qualification,a.reverse)
        prepare() # Validate real source fixtures before reserving any GPU or calling a model.
        (out/'selected-orders.json').write_bytes(Path(a.orders).read_bytes())
        (out/'budget.json').write_bytes((ROOT/'configs/selected-budget.json').read_bytes())
        planned=schedule(tuple(a.gpus))
        dump(out/'manifest.json',{'version':'memrsi-feedback-v1.4r1','gpus':a.gpus,'schedule':planned,
            'planned_test_trials':len(planned),'test_histories':histories(),
            'previous_test_histories_now_excluded':old_histories(),'full_development_histories':DEVELOPMENT_HISTORIES,
            'test_scope':'new priority sequences; known task families and physical initial states',
            'physical_sources':{n:sha(ROOT/n) for n in PHYSICAL_FILES},
            'baseline':'unchanged PAOS core/native archive/session; identical public action/capacity adapters',
            'manual_repairs':'task-record compiler and exact-quote guidance selector; not learned improvements',
            'RSI_credit':'evolved memory representation/read/retention design versus identical fixed seed architecture',
            'evaluation_policy_frozen':True,'no_expected_answers_to_actor':True,'no_finish_veto':True,
            'episode_retries':2,'inherited_attempts_count_towards_limit':True,'recovery_parent':'/data/stormlab/xi/paos/results/memrsi-feedback-v1_4-20261011T160858Z/experiment','max_proposals':2,'max_full_development_trials':24,
            'memory_budget':json.loads((out/'budget.json').read_text()),
            'gateway':'existing Luna gateway; request lock remains serialized',
            'promotion_failure':'stop and release GPUs, no fallback evaluation'})
        experiment=Experiment(out,a.gpus,out/'selected-orders.json',out/'budget.json',stop)
        experiment.acquire()
        learning=asyncio.run(learn(out/'learning',experiment))
        dump(out/'policies/fixed.json',SEED);policies={'fixed':out/'policies/fixed.json'}
        if learning['status']=='accepted':
            candidate=json.loads((out/'learning/accepted-policy.json').read_text())
            if digest(candidate)==digest(SEED):raise RuntimeError('unchanged_evolved_policy')
            dump(out/'policies/evolved.json',candidate);policies['evolved']=out/'policies/evolved.json'
            dump(out/'policy-freeze.json',{'base':digest(SEED),'evolved':digest(candidate)})
            selected=planned
        else:
            report={'status':'no_accepted_improvement','learning_status':learning['status'],
                    'planned_test':len(planned),'launched_test':0}
            dump(out/'skipped.json',{'reason':'no_accepted_improvement','trials':[r['trial_id'] for r in planned]})
            return 0
        experiment.state('evaluation',planned=len(selected))
        rows=experiment.batch(selected,policies,out/'evaluation')
        dump(out/'summary.json',summarize(rows,selected));dump(out/'paired.json',paired(rows))
        report={'status':'completed','planned':len(selected),'terminal':len(rows),
            'learning_status':learning['status'],'summary':summarize(rows,selected)}
    except Exception as exc:
        # Exception strings can contain upstream credentials. Keep only known codes.
        safe={'technical_hold','queue_cancelled','source_changed','baseline_probe_invalid',
            'learning_call_budget_exhausted','gpu_busy_without_standard_lease','reserved_policy_port_busy',
            'gateway_model_mismatch','policy_start_failed','gpu_lock_wait_budget_exhausted',
            'provider_error','native_session_archival_failed'}
        report={'status':'cancelled' if stop.is_set() and str(exc)=='queue_cancelled' else 'failed',
            'error_type':type(exc).__name__,'error_code':str(exc) if str(exc) in safe else 'inspect_structured_outputs'}
    finally:
        if experiment:experiment.close()
        dump(out/'report.json',report)
        if experiment:experiment.state(report['status'],report=report)
    return 0 if report['status']=='completed' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('output','orders','qualification','reverse'):p.add_argument('--'+k,required=True)
    p.add_argument('--gpus',type=int,nargs='+',required=True)
    raise SystemExit(main(p.parse_args()))
