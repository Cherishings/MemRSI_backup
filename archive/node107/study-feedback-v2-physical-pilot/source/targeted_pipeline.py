"""RSI only. Reuse fixed/native results strictly after sealed testing."""
import argparse,asyncio,json,hashlib,os,signal,threading,time
from pathlib import Path
from durable_queue import read
from run_queue import identity,ROOT
from replay import dump
from physical_runner import PhysicalRunner,same_process
from parallel_runtime import GpuPool
from targeted_learning import DevelopmentExperiment,run as learn
from targeted_validation import run as validate
from stream_design import compile_procedures,SEED_PROCEDURES,development_rows
from unified_pipeline import gateway_contract,matched_summary
from model_provider import LEARNING_LEDGER
from targeted_pilot import bootstrap_pilot

def make_runner(out,stop,gpus=(0,1,2)):
    directory=Path(out)/('gpu-workers-'+str(time.time_ns()))
    directory.mkdir(parents=True,exist_ok=False)
    return PhysicalRunner(directory,stop,tuple(gpus))

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
        dump(out/'manifest.json',{'version':'targeted-v1.8','gpus':list(gpus),'schedule':heldout,'source':str(source),
          'baseline_methods_unchanged':True,'baseline_results_not_available_to_learner':True,'development':16,'reserved_validation':4,
          'selection_changed_from_v1_7':'positive net gain allowed exploratory promotion; cycle0 pilot reused after inspecting prior results; independent validation unchanged; no pooling with old RSI','pilot':pilot})
        bootstrap_pilot(pilot,out/'learning')
        gateway_contract(stop)
        runner=make_runner(out,stop,gpus);runner.acquire(lambda status,**k:dump(out/'progress.json',dict(phase=status,**k)))
        exp=DevelopmentExperiment(out/'evolved',2,out/'selected-orders.json',out/'budget.json',stop,runner,GpuPool(tuple(gpus),stop),old_learning=old)
        def learning_and_validation():
            async def go():
                learning=await learn(out/'learning',exp,out/'budget.json',old)
                if learning['status']=='no_accepted_update':return learning,None
                LEARNING_LEDGER.set(out/'learning/learning-call-ledger.json')
                exp.state('sealed_validation')
                source_rows=[]
                for f in old.glob('round-*/physical/rows.json'):
                    source_rows.extend(r for r in read(f,[]) if r['trial_id'] in {'dev-16','dev-17','dev-18','dev-19'})
                if len(source_rows)!=4:raise RuntimeError('reserved_validation_sources_incomplete')
                candidate=read(out/'learning/candidate-policy.json')
                report=await validate(source_rows,out/'validation',compile_procedures(SEED_PROCEDURES),candidate,out/'budget.json',exp.wait_gateway)
                return learning,report
            return asyncio.run(go())
        learning,validation=learning_and_validation()
        if validation is None or not validation['passed']:
            dump(out/'report.json',{'status':'learning_finished_no_qualified_policy','learning':learning,'validation':validation,
                 'heldout_runs':0,'no_seed_relabelled_as_evolved':True});return 0
        frozen=read(out/'learning/candidate-policy.json');dump(out/'frozen-policy.json',frozen)
        dump(out/'freeze.json',{'sha256':hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest(),'time':time.time(),'validation_no_feedback_to_learner':True})
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
