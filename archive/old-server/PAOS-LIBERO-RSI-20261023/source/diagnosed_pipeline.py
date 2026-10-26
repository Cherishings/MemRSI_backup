"""Preserve the successful fixed runtime; learn only G/U; reuse old baselines."""
import argparse
import asyncio
import hashlib
import json
import os
import signal
import threading
import time
from pathlib import Path
from durable_queue import read
from run_queue import ROOT, identity
from replay import dump
from physical_runner import PhysicalRunner, same_process
from parallel_runtime import GpuPool
from targeted_learning import DevelopmentExperiment
from diagnosed_learning import run as learn
from stream_design import compile_procedures, SEED_PROCEDURES, development_rows
from unified_pipeline import gateway_contract, matched_summary
from bounded_edits import recover_last_submission


class Control:
    def __init__(self, out, stop): self.out = Path(out); self.stop = stop
    def state(self, phase, **fields):
        dump(self.out/'progress.json', dict(phase=phase, updated_unix=time.time(), **fields))
    def wait_gateway(self):
        return gateway_contract(self.stop, lambda: self.state('waiting_gateway_no_trial_started'))


def audit_runtime(previous, out):
    # All Python files present in the old baseline, not just selected interfaces.
    hashes = {}
    for p in Path(previous['code']).glob('*.py'):
        local = ROOT/p.name
        if not local.exists() or local.read_bytes() != p.read_bytes():
            raise RuntimeError('fixed_runtime_changed:'+p.name)
        hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    old = Path(previous['result'])/'fixed/evaluation/comparison/h01-i0-r0/fixed/attempt-01/applied-memory-policy.json'
    seed = compile_procedures(SEED_PROCEDURES)
    if seed != read(old):
        raise RuntimeError('seed_not_actual_fixed_policy')
    dump(Path(out)/'runtime-audit.json', dict(files=hashes, fixed_policy_exact_match=True,
        no_delta_store=True, source=previous['code'], old_results_not_overwritten=True))
    return seed


def check_predecessor(prior,out,seed):
    source=Path(prior['result'])
    report=read(source/'report.json',{})
    if report.get('status')!='learning_finished_no_qualified_policy':
        raise RuntimeError('predecessor_not_completed_unpromoted_learning')
    if read(source/'fixed-seed-policy.json')!=seed:raise RuntimeError('predecessor_seed_changed')
    if read(source/'learning/learning-call-ledger.json')['calls']!=7867:
        raise RuntimeError('predecessor_budget_changed')
    dump(Path(out)/'predecessor-audit.json',dict(source=str(source),original_results_preserved=True,
        old_proposals_not_adopted=True,scoring_unchanged=True,diagnosis_uses_development_only=True))


def main(out, after, pilot, gpus):
    if not gpus or len(set(gpus)) != len(gpus) or not set(gpus) <= set(range(7)):
        raise ValueError('only_gpu0_to6_allowed')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    stop = threading.Event(); runner = None; control = Control(out, stop)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    dump(out/'coordinator.json', identity(os.getpid()))
    try:
        previous = read(after); prior = read(pilot)
        if same_process(previous['coordinator']) or same_process(prior['coordinator']):
            raise RuntimeError('previous_coordinator_still_running')
        source = Path(previous['result'])
        for name in ('budget.json', 'selected-orders.json'):
            dest = out/name
            if dest.exists() and dest.read_bytes() != (source/name).read_bytes():
                raise RuntimeError('input_changed')
            dest.write_bytes((source/name).read_bytes())
        seed = audit_runtime(previous, out); dump(out/'fixed-seed-policy.json', seed)
        check_predecessor(prior,out,seed)
        schedule = read(source/'manifest.json')['schedule']
        evaluation = [r for r in schedule if r['arm'] == 'evolved']
        if len(evaluation) != 48 or {r['history'] for r in evaluation} & {r['history'] for r in development_rows()}:
            raise RuntimeError('split_or_count_mismatch')
        dump(out/'manifest.json', dict(version='bounded-v2.2', gpus=list(gpus), schedule=evaluation,
            source=str(source), baseline_reruns=0, bounded_runtime_byte_identical=True,
            learning_changes_only='complete-transition diagnosis and rejected-edit regression feedback; one local G/U edit per cycle',
            old_comparison_cases_audited_by_developer=True,
            evaluation_scope='paired regression comparison; not an untouched new benchmark',
            baseline_results_never_optimizer_inputs=True))
        control.wait_gateway()
        v19 = read('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/portable-runtime-20261023/paos/qwen-deploy/latest-memrsi-trajectory-v1_9.json')
        learning = asyncio.run(learn(out/'learning', control, out/'budget.json', v19['result'], prior['result']))
        if learning['status'] != 'candidate_ready_for_test':
            dump(out/'report.json', dict(status='learning_finished_no_qualified_policy', learning=learning,
                physical_runs=0, seed_not_relabelled_as_evolved=True))
            control.state('learning_finished_no_qualified_policy')
            return 0
        frozen = read(out/'learning/candidate-policy.json'); dump(out/'frozen-policy.json', frozen)
        dump(out/'freeze.json', dict(sha256=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest(),
            time=time.time(), no_evaluation_feedback_to_learning=True))
        directory = out/('gpu-workers-'+str(time.time_ns())); directory.mkdir()
        runner = PhysicalRunner(directory, stop, tuple(gpus))
        runner.acquire(lambda status, **kw: control.state(status, **kw))
        control.state('bounded_physical_evaluation', planned=48, gpus=list(gpus))
        exp = DevelopmentExperiment(out/'evolved', 2, out/'selected-orders.json', out/'budget.json',
            stop, runner, GpuPool(tuple(gpus), stop), old_learning=source/'evolved-r4/learning')
        rows = exp.batch(evaluation, {'evolved':out/'frozen-policy.json'}, out/'evaluation')
        baselines = read(source/'native/evaluation/rows.json') + read(source/'fixed/evaluation/rows.json')
        dump(out/'paired-summary.json', matched_summary(baselines+rows, schedule))
        dump(out/'report.json', dict(status='completed', physical_runs=len(rows),
            baseline_runs_reused=len(baselines), promotions=learning['promotions'],
            repair_alone_not_rsi_gain=True))
        control.state('completed', terminal=len(rows)); return 0
    except Exception as ex:
        dump(out/'report.json', dict(status='blocked', error_type=type(ex).__name__,
            code=str(ex) if isinstance(ex,(RuntimeError, ValueError, AssertionError)) else 'inspect_structured_evidence'))
        return 2
    finally:
        if runner: runner.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--output', required=True)
    p.add_argument('--after', required=True); p.add_argument('--pilot', required=True)
    p.add_argument('--gpus', default='0,1,2,3,4'); a = p.parse_args()
    raise SystemExit(main(a.output, a.after, a.pilot, tuple(map(int,a.gpus.split(',')))))
