"""Learn now without a GPU; queue physical transfer behind the live comparison."""
import argparse,asyncio,json,os,signal,threading,time
from pathlib import Path
from replay import dump
from run_queue import identity
from evolve_v15 import run as learn
from memory_policy import BASE,digest
from feedback_protocol import transfer_histories
from experiment_recovery import Experiment
from physical_runner import same_process

def schedule(gpus,has_candidate):
    rows=[];arms=['native','fixed']+(['candidate'] if has_candidate else [])
    for hi,h in enumerate(transfer_histories()):
        for init in (0,1):
            k=hi*2+init;offset=k%len(arms)
            for arm in arms[offset:]+arms[:offset]:
                rows.append(dict(trial_id=f't{hi}-i{init}/{arm}',condition=f't{hi}-i{init}',
                    history=h,init=init,repeat=0,arm=arm,gpu=gpus[k%len(gpus)]))
    return rows

def summarize(rows,planned):
    out={}
    for arm in sorted({r['arm'] for r in planned}):
        rs=[r for r in rows if r['arm']==arm];n=sum(r['arm']==arm for r in planned)
        reached=sum(r.get('reached_checkpoints',0) for r in rs);correct=sum(r.get('correct_checkpoints',0) for r in rs)
        counts={s:sum(r['status']==s for r in rs) for s in {r['status'] for r in rs}}
        out[arm]=dict(planned=n,terminal=len(rs),status_counts=counts,planned_checkpoints=7*n,
                     reached=reached,correct=correct,coverage=reached/(7*n),
                     accuracy_given_reached=correct/reached if reached else None)
    return out

def main(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    stop=threading.Event();ex=None
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    dump(out/'coordinator.json',identity(os.getpid()))
    parent=json.loads(Path(args.after).read_text());parentout=Path(parent['result'])
    for name in ('selected-orders.json','budget.json'):(out/name).write_bytes((parentout/name).read_bytes())
    dump(out/'manifest.json',{'version':'v1.5r1-format-recovery','resumed_learning':args.resume_learning,'gpus':args.gpus,
       'two_development_rounds':True,'pending_behind':parent,'transfer_histories':transfer_histories(),
       'transfer_max_trials':24,'scope':'new priority orders, known kitchens/physical states',
       'physical_schedule_unchanged':True,'current_80_test_results_not_read_by_optimizer':True,
       'no_early_stop_for_no_gain':True,'candidate_label_does_not_imply_improvement':True})
    report={'status':'failed'}
    try:
        learning=asyncio.run(learn(out/'learning',args.resume_learning))
        dump(out/'policies/fixed.json',BASE)
        policies={'fixed':out/'policies/fixed.json'}
        if (out/'learning/candidate-policy.json').exists():
            candidate=json.loads((out/'learning/candidate-policy.json').read_text())
            if digest(candidate)==digest(BASE):raise RuntimeError('unchanged_candidate')
            dump(out/'policies/candidate.json',candidate);policies['candidate']=out/'policies/candidate.json'
        planned=schedule(args.gpus,'candidate' in policies);dump(out/'transfer-schedule.json',planned)
        # Own no GPU while waiting. Standard locks also protect against lingering children.
        while same_process(parent['coordinator']):
            dump(out/'progress.json',{'status':'waiting_prior_comparison','learning_status':learning['status'],
              'development_promotions':learning['development_promotions'],'updated_unix':time.time()})
            if stop.wait(30):raise RuntimeError('queue_cancelled')
        if stop.is_set():raise RuntimeError('queue_cancelled')
        ex=Experiment(out,args.gpus,out/'selected-orders.json',out/'budget.json',stop)
        ex.acquire()
        rows=ex.batch(planned,policies,out/'evaluation',False)
        summary=summarize(rows,planned);dump(out/'summary.json',summary)
        report={'status':'completed','learning_status':learning['status'],
                'development_promotions':learning['development_promotions'],
                'window_validated_gain':learning['validated_gain'],'summary':summary}
    except Exception as exc:
        safe={'queue_cancelled','source_changed','baseline_probe_invalid','learning_call_budget_exhausted',
              'provider_error','optimizer_protocol_failure','optimizer_schema_failure','unchanged_candidate'}
        report={'status':'cancelled' if stop.is_set() else 'failed','error_type':type(exc).__name__,
                'error_code':str(exc) if str(exc) in safe else 'inspect_structured_outputs'}
    finally:
        if ex:ex.close()
        dump(out/'report.json',report);dump(out/'progress.json',{'status':report['status']})
    return 0 if report['status']=='completed' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--after',required=True)
    p.add_argument('--gpus',nargs='+',type=int,required=True);p.add_argument('--resume-learning');a=p.parse_args()
    if len(set(a.gpus))!=len(a.gpus) or not a.gpus or set(a.gpus)-{0,1,3,4,5,6,7}:p.error('invalid GPUs')
    raise SystemExit(main(a))
