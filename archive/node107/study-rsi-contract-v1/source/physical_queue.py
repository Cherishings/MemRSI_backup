"""Frozen 24-run physical pilot: native versus fixed and evolved MemRSI.

The 24-trial schedule and base memory policy are frozen before any comparison.
Native/fixed trials proceed while CPU evolution runs; its final policy is frozen
before the last eight evolved trials. No physical outcome feeds evolution.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import time

from physical_runner import PhysicalRunner, wait_for_policy
from memory_policy import load
from run_queue import ROOT, dump, identity
from stress_protocol import CASES

ARMS = ('native', 'memrsi_fixed', 'memrsi_evolved')
PHYSICAL_FILES = ('native_world.py', 'world_client.py', 'check_case.py',
    'paired_sampling.py', 'serve_paired_policy.py', 'retry_recovery.py', 'osc_handoff.py')


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schedule():
    first,evolved=[],[]
    for length_index,jobs in enumerate((16,32)):
        for case_index,case in enumerate(CASES):
            for hi,history in enumerate(('one_first','two_first')):
                scenario_id=f'{case}-{history}-jobs{jobs}-i{case_index%2}-v{(case_index+length_index)%2}'
                arms=('native','memrsi_fixed') if (case_index+hi+length_index)%2==0 else ('memrsi_fixed','native')
                for arm in arms+('memrsi_evolved',):
                    (evolved if arm=='memrsi_evolved' else first).append(dict(
                        trial_id=f'{scenario_id}/{arm}',scenario_id=scenario_id,case=case,history=history,jobs=jobs,
                        init=case_index%2,variant=(case_index+length_index)%2,gpu=hi,arm=arm,
                        phase='evolved' if arm=='memrsi_evolved' else 'native_fixed',
                        effective_arm='native' if arm=='native' else 'memrsi'))
    return first+evolved


def history_pair_audit(rows):
    from portable_metrics import information_pair,normalize_libero
    groups={}
    for row in rows:
        if 'planned_checkpoint' not in row:continue
        groups.setdefault((row['case'],row['arm'],row['jobs']),{})[row['history']]=row
    audits=[]
    for (case,arm,jobs),g in groups.items():
        if set(g)=={'one_first','two_first'}:
            pair=information_pair(*(normalize_libero(g[h]) for h in ('one_first','two_first')))
            audits.append(dict(case=case,arm=arm,jobs=jobs,**pair))
    return audits


def summary(rows, planned):
    arms = {}
    for arm in ARMS:
        selected = [r for r in rows if r['arm'] == arm]
        counts = {}
        for row in selected:
            counts[row['status']] = counts.get(row['status'], 0) + 1
        arms[arm] = {
            'planned_trials': sum(r['arm'] == arm for r in planned),
            'terminal_trials': len(selected), 'status_counts': counts,
            'planned_checkpoints_in_terminal_trials': sum(r.get('planned_checkpoint', 0) for r in selected),
            'arrived_checkpoints': sum(r.get('arrived_checkpoint', 0) for r in selected),
            'answered_checkpoints': sum(r.get('answered_checkpoint', 0) for r in selected),
            'correct_checkpoints': sum(r.get('correct_checkpoint', 0) for r in selected)}
    return arms


def main(args):
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    stop = threading.Event()
    runner = PhysicalRunner(out, stop)
    rows, active, lock = [], {}, threading.RLock()
    planned = schedule()
    dump(out / 'coordinator.json', identity(os.getpid()))
    (out / 'selected-orders.json').write_bytes(Path(args.orders).read_bytes())
    baseline = load(args.base_policy)
    (out / 'policies').mkdir()
    dump(out / 'policies/fixed.json', baseline)
    manifest = {
        'version': 'memrsi-evidence-v2', 'planned_trials': len(planned),
        'planned_scenarios': 16, 'arms': ARMS, 'gpus': [0, 1], 'model': 'gpt-5.6-luna',
        'schedule': planned, 'source_sha256': {p.name: file_hash(p) for p in ROOT.glob('*.py')},
        'physical_source_sha256': {name: file_hash(ROOT / name) for name in PHYSICAL_FILES},
        'orders_sha256': file_hash(out / 'selected-orders.json'),
        'base_policy_source': str(Path(args.base_policy).resolve()),
        'base_policy_sha256': file_hash(out / 'policies/fixed.json'),
        'evolution_policy_source': str(Path(args.evolution_policy).resolve()),
        'sessions': '16 or 32 actual kitchen jobs, one native /new after every two jobs: 8 or 16 rollovers',
        'scoring': 'All prespecified outcomes retained. Capability failures are never rerun. Planned, arrived, answered and correct checkpoints reported separately.',
        'dispatch': 'Only the model-chosen action is dispatched. Evaluator expected actions are not passed into actor memory or action calls.',
        'comparison': 'Each scenario is matched across three arms. Histories share init/job rotation. Exact current-input, action-contract and station-state hashes are audited for all four cases. Resume/revise/cancel share the same partially completed table-one prefix in both histories.',
        'baseline': 'Native PAOS memory, native /new and original core with a common declared physical-action adapter. Not an unmodified end-to-end deployment.',
        'evaluation_feedback_to_learning': False,
        'phase_order': 'First 32 native/fixed trials run concurrently with CPU evolution. A global barrier then freezes the final policy before all 16 evolved trials.',
        'temporal_confound': 'Evolved trials occur later than native/fixed trials. Native/fixed order is balanced, but evolved timing is not randomized; backend/load changes are possible confounders.',
        'scope': 'Real simulated gripper; scene routing is scheduled, not robot navigation. Familiar native LIBERO task families at a new 16/32-job schedules, not unseen-family generalization.',
        'episode_retries': 0, 'policy_restarts': 0,
        'infra_stop': 'A lane stops after two consecutive infrastructure failures; pending cases remain pending.'}
    dump(out / 'manifest.json', manifest)

    def state(status='running', **extra):
        with lock:
            dump(out / 'progress.json', dict(status=status, planned=len(planned),
                terminal=len(rows), active=dict(active), updated_unix=time.time(), **extra))

    def stopped(signum, frame):
        stop.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stopped)

    infra_counts = {0: 0, 1: 0}

    def lane(gpu, policies, phase):
        if infra_counts[gpu] >= 2:
            return
        for row in (r for r in planned if r['gpu'] == gpu and r['phase'] == phase):
            if stop.is_set():
                break
            def progress(info):
                with lock:
                    active[str(gpu)] = dict(info, phase=phase)
                    state()
            policy = policies.get(row['arm'])
            result = runner.episode(gpu, row, out / 'selected-orders.json', policy,
                out / 'evaluation' / row['trial_id'], progress, timeout=args.episode_timeout)
            with lock:
                rows.append(result)
                dump(out / 'rows.json', rows)
                dump(out / 'summary.json', summary(rows, planned))
                dump(out / 'history-pairs.json', history_pair_audit(rows))
                from portable_metrics import normalize_libero,summarize
                dump(out / 'portable-metrics.json', {arm: summarize([normalize_libero(r) for r in rows if r['arm']==arm and 'planned_checkpoint' in r],16) for arm in ARMS})
                from portable_metrics import learning_gain
                groups={arm:[normalize_libero(r) for r in rows if r['arm']==arm and 'planned_checkpoint' in r] for arm in ARMS}
                dump(out / 'learning-gain.json',learning_gain(groups['memrsi_fixed'],groups['memrsi_evolved']))
                state()
            infra_counts[gpu] = infra_counts[gpu] + 1 if result['status'] == 'infrastructure_failure' else 0
            if infra_counts[gpu] >= 2:
                progress({'status': 'paused_infrastructure', 'pending_retained': True})
                return
        with lock:
            active[str(gpu)] = {'status': 'cancelled' if stop.is_set() else 'phase_terminal', 'phase': phase}
            state()

    def source_guard():
        if any(not (ROOT / name).is_file() or file_hash(ROOT / name) != expected
               for name, expected in manifest['source_sha256'].items()):
            raise RuntimeError('source_changed_after_queue_launch')

    def run_phase(policies, phase):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(lane, gpu, policies, phase) for gpu in (0, 1)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except BaseException:
                    stop.set()
                    raise

    evolved = None
    try:
        source_guard()
        policies = {'memrsi_fixed': out / 'policies/fixed.json'}
        dump(out / 'frozen-policies.json', {
            'policy_sha256': {'memrsi_fixed': file_hash(policies['memrsi_fixed'])},
            'evolved_policy_status': 'not_frozen_no_evolved_trial_started',
            'identical_policies': None, 'freeze_before_respective_arm': True})
        runner.acquire(state, wait_seconds=args.wait_hours * 3600)
        state('running_native_fixed', phase='native_fixed')
        run_phase(policies, 'native_fixed')
        # Joining both lanes above is a global barrier: all 32 first-phase
        # outcomes must exist before either lane may start an evolved trial.
        if len(rows) == 32 and not stop.is_set():
            evolved = wait_for_policy(args.evolution_policy,
                time.monotonic() + args.wait_hours * 3600, stop, state)
            dump(out / 'policies/evolved.json', evolved)
            policies['memrsi_evolved'] = out / 'policies/evolved.json'
            hashes = {name: file_hash(path) for name, path in policies.items()}
            dump(out / 'frozen-policies.json', {
                'policy_sha256': hashes, 'identical_policies': baseline == evolved,
                'evolved_policy_status': 'frozen_after_first_32_before_evolved_trials',
                'first_phase_terminal_trials': len(rows),
                'interpretation': 'If identical, both labels remain explicit repeated evaluations; no learned-change benefit may be claimed.',
                'freeze_before_respective_arm': True})
            source_guard()
            state('running_evolved', phase='evolved')
            run_phase(policies, 'evolved')
        status = 'completed' if len(rows) == len(planned) else 'cancelled' if stop.is_set() else 'paused_infrastructure'
        done = {r['trial_id'] for r in rows}
        dump(out / 'report.json', {'status': status, 'planned_trials': len(planned),
            'terminal_trials': len(rows), 'arms': summary(rows, planned),
            'identical_policies': baseline == evolved if evolved is not None else None,
            'temporal_confound': manifest['temporal_confound'],
            'history_pairs': history_pair_audit(rows),
            'pending_trial_ids': [r['trial_id'] for r in planned if r['trial_id'] not in done],
            'all_outcomes_retained': True, 'evaluation_feedback_to_learning': False})
        state(status)
    except Exception as exc:
        # Only controlled error identifiers, never raw provider/Loguru exceptions.
        safe_codes = {'queue_cancelled', 'evolution_failed', 'evolution_wait_budget_exhausted', 'gpu_lock_wait_budget_exhausted',
            'reserved_policy_port_busy', 'gpu_busy_without_standard_lease', 'gateway_model_mismatch',
            'policy_start_failed', 'episode_output_already_exists', 'source_changed_after_queue_launch', 'policy_schema', 'policy_length'}
        code = str(exc) if str(exc) in safe_codes else 'inspect_structured_outputs'
        dump(out / 'queue-failure.json', {'type': type(exc).__name__, 'code': code})
        done = {r['trial_id'] for r in rows}
        dump(out / 'report.json', {'status': 'failed', 'error_code': code,
            'planned_trials': len(planned), 'terminal_trials': len(rows),
            'arms': summary(rows, planned), 'history_pairs': history_pair_audit(rows),
            'pending_trial_ids': [r['trial_id'] for r in planned if r['trial_id'] not in done],
            'all_outcomes_retained': True, 'evaluation_feedback_to_learning': False})
        state('failed', error_code=code)
        raise RuntimeError(code) from None
    finally:
        runner.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--orders', required=True)
    parser.add_argument('--evolution-policy', required=True)
    parser.add_argument('--base-policy', required=True)
    parser.add_argument('--wait-hours', type=float, default=12)
    parser.add_argument('--episode-timeout', type=int, default=10800)
    main(parser.parse_args())
