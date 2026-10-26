"""RSI only. Reuse fixed/native results strictly after sealed testing."""
import argparse,asyncio,json,hashlib,os,signal,threading,time
from pathlib import Path
from durable_queue import read
from run_queue import identity,ROOT
from replay import dump
from physical_runner import PhysicalRunner,same_process
from parallel_runtime import GpuPool
from targeted_learning import DevelopmentExperiment
from regression_evolution import run as learn
from stream_design import compile_procedures,SEED_PROCEDURES,development_rows
from unified_pipeline import gateway_contract,matched_summary
from model_provider import LEARNING_LEDGER

def make_runner(out,stop,gpus=(0,1,2)):
    directory=Path(out)/('gpu-workers-'+str(time.time_ns()))
    directory.mkdir(parents=True,exist_ok=False)
    return PhysicalRunner(directory,stop,tuple(gpus))

class LearningControl:
    def __init__(self,out,stop):self.out=Path(out);self.stop=stop
    def state(self,phase,**fields):dump(self.out/'progress.json',dict(phase=phase,updated_unix=time.time(),**fields))
    def wait_gateway(self):
        return gateway_contract(self.stop,lambda:self.state('waiting_gateway_no_trial_started'))

def main(out,after,gpus=(0,1,2),pilot=None):
    if not gpus or len(set(gpus))!=len(gpus) or not set(gpus)<=set(range(7)):raise ValueError('only_gpu0_to6_allowed')
    out=Path(out);out.mkdir(parents=True,exist_ok=True);stop=threading.Event();runner=None
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    dump(out/'coordinator.json',identity(os.getpid()))
    try:
        previous=read(after);source=Path(previous['result']);old=source/'evolved-r4/learning'
        while same_process(previous['coordinator']):
            dump(out/'progress.json',{'phase':'waiting_old_rsi_exit','updated_unix':time.time()})
            if stop.wait(5):raise RuntimeError('queue_cancelled')
        for name in ('budget.json','selected-orders.json'):
            dest=out/name
            if dest.exists() and dest.read_bytes()!=(source/name).read_bytes():raise RuntimeError('input_changed')
            dest.write_bytes((source/name).read_bytes())
        schedule=read(source/'manifest.json')['schedule'];heldout=[r for r in schedule if r['arm']=='evolved']
        assert len(heldout)==48
        assert not {r['history'] for r in heldout}&{r['history'] for r in development_rows()}
        # Audit identical public actor/executor modules against the completed baselines.
        critical=['agent_adapter.py','twenty_agent.py','memory_ops.py','memory_budget.py','stress_protocol.py','stress_workflow.py','model_provider.py','physical_runner.py','action_catalog.py','execution_contract.py','feedback_protocol.py']
        for name in critical:
            if (ROOT/name).read_bytes()!=(Path(previous['code'])/name).read_bytes():raise RuntimeError('baseline_comparability_changed:'+name)
        dump(out/'manifest.json',{'version':'regression-feedback-v1.10','gpus':list(gpus),'schedule':heldout,'source':str(source),
          'baseline_methods_unchanged':True,'baseline_results_not_available_to_learner':True,'development_replays':12,'audited_old_validation_not_reused':True,
          'change_from_v1_9':'learn from actual rejected-candidate regressions; exactly reuse verified parent caches; 12 development pairs; unchanged whole-trajectory scoring and acceptance rule; defer GPU allocation until physical testing','pilot':pilot})
        prior=read(pilot)
        if not prior or same_process(prior['coordinator']):raise RuntimeError('prior_missing_or_running')
        if read(Path(prior['result'])/'report.json',{}).get('status')!='learning_finished_no_qualified_policy':raise RuntimeError('unexpected_prior_state')
        gateway_contract(stop)
        controller=LearningControl(out,stop)
        learning=asyncio.run(learn(out/'learning',controller,out/'budget.json',prior))
        if learning['status']=='no_accepted_update':
            dump(out/'report.json',{'status':'learning_finished_no_qualified_policy','learning':learning,
                 'heldout_runs':0,'no_seed_relabelled_as_evolved':True});return 0
        frozen=read(out/'learning/candidate-policy.json');dump(out/'frozen-policy.json',frozen)
        dump(out/'freeze.json',{'sha256':hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest(),'time':time.time(),'heldout_no_feedback_to_learner':True,'old_validation_not_claimed_independent':True})
        runner=make_runner(out,stop,gpus);runner.acquire(lambda status,**k:dump(out/'progress.json',dict(phase=status,**k)))
        exp=DevelopmentExperiment(out/'evolved',2,out/'selected-orders.json',out/'budget.json',stop,runner,GpuPool(tuple(gpus),stop),old_learning=old)
        rows=exp.batch(heldout,{'evolved':out/'frozen-policy.json'},out/'evaluation')
        # Comparison only after all learning and heldout executions are complete.
        baselines=read(source/'native/evaluation/rows.json')+read(source/'fixed/evaluation/rows.json')
        dump(out/'paired-summary.json',matched_summary(baselines+rows,schedule))
        dump(out/'report.json',{'status':'completed','heldout_runs':len(rows),'baseline_runs_reused':len(baselines),'promotions':learning['promotions']})
        return 0
    except Exception as ex:
        dump(out/'report.json',{'status':'blocked','error_type':type(ex).__name__,
          'file':Path(ex.filename).name if isinstance(ex,FileNotFoundError) and ex.filename else None,
          'code':str(ex) if isinstance(ex,(RuntimeError,ValueError,AssertionError)) else 'inspect_structured_evidence'})
        return 2
    finally:
        if runner:runner.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--after',required=True);p.add_argument('--pilot',required=True);p.add_argument('--gpus',default='0,1,2');a=p.parse_args()
    raise SystemExit(main(a.output,a.after,tuple(map(int,a.gpus.split(','))),a.pilot))
