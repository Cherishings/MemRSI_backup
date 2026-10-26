"""Run the paired comparison regardless of whether evolution found a candidate."""
import argparse,json,os,signal,threading
from pathlib import Path
from replay import dump
from run_queue import ROOT,identity
from experiment_recovery import Experiment
from feedback_protocol import schedule
from memory_policy import digest,BASE as SEED
from feedback_queue import summarize
PARENT=Path('/data/stormlab/xi/paos/results/memrsi-feedback-v1_4r1-20261011T164157Z/experiment')

def planned_rows(gpus):
    groups={}
    for r in schedule(tuple(gpus)):
        if r['arm']=='evolved':continue
        groups.setdefault((r['condition'],r['repeat']),[]).append(r)
    out=[]
    for i,pair in enumerate(groups.values()):
        arms=('native','fixed') if i%2==0 else ('fixed','native')
        out.extend(next(r for r in pair if r['arm']==a) for a in arms)
    return out

def pair_summary(rows):
    pairs={}
    for r in rows:pairs.setdefault((r['condition'],r['repeat']),{})[r['arm']]=r
    return [{'condition':k[0],'repeat':k[1],'complete_pair':set(v)=={'native','fixed'},
        'arms':{a:{'status':r['status'],'reached':r.get('reached_checkpoints',0),'correct':r.get('correct_checkpoints',0)} for a,r in v.items()}}
        for k,v in pairs.items()]

def main(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    stop=threading.Event();e=None;report={'status':'failed'}
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    dump(out/'coordinator.json',identity(os.getpid()))
    planned=planned_rows(a.gpus)
    try:
        for n in ('selected-orders.json','budget.json'):(out/n).write_bytes((PARENT/n).read_bytes())
        base=json.loads((PARENT/'learning/base-policy.json').read_text())
        if digest(base)!=digest(SEED):raise RuntimeError('policy_mismatch')
        dump(out/'policies/fixed.json',base)
        dump(out/'manifest.json',{'version':'v1.4-comparison','gpus':a.gpus,'planned_trials':80,
            'arms':{'native':'original PAOS with shared execution/capacity adapters','fixed':'current MemRSI v1.4 seed; no learned update claimed'},
            'schedule':planned,'parent':str(PARENT),'parent_8_development_trials_not_added_to_test':True,
            'policy_sha256':digest(base),'prior_learning_promotions':0,'test_feedback_to_optimizer':False,
            'same_initial_state_and_history_per_pair':True,'balanced_arm_order':True,
            'memory_budget':json.loads((out/'budget.json').read_text()),
            'max_episode_attempts':3,'capability_failure_retries':0,
            'stop_after_good_results':False,'stop_after_no_learning_gain':False,
            'isolated_technical_failures_cancel_siblings':False,
            'execution':'20 serial sessions with actual simulated gripper per episode; parallel independent episodes'})
        e=Experiment(out,a.gpus,out/'selected-orders.json',out/'budget.json',stop);e.acquire()
        e.state('comparison',planned=len(planned))
        rows=e.batch(planned,{'fixed':out/'policies/fixed.json'},out/'evaluation',False)
        summary={k:v for k,v in summarize(rows,planned).items() if k in ('native','fixed')}
        for arm,d in summary.items():d['planned_checkpoints_all']=7*sum(r['arm']==arm for r in planned)
        dump(out/'summary.json',summary);dump(out/'paired.json',pair_summary(rows))
        report={'status':'completed','planned':len(planned),'terminal':len(rows),'summary':summary,
                'learned_RSI_gain_claimed':False,'evolved_arm_not_fabricated':True}
    except Exception as exc:
        safe={'queue_cancelled','source_changed','policy_mismatch','gpu_busy_without_standard_lease',
              'reserved_policy_port_busy','gateway_model_mismatch','policy_start_failed','gpu_lock_wait_budget_exhausted'}
        report={'status':'cancelled' if stop.is_set() else 'failed','error_type':type(exc).__name__,
                'error_code':str(exc) if str(exc) in safe else 'inspect_structured_outputs'}
    finally:
        if e:e.close()
        dump(out/'report.json',report)
        if e:e.state(report['status'],report=report)
    return 0 if report['status']=='completed' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--gpus',nargs='+',type=int,required=True)
    raise SystemExit(main(p.parse_args()))
