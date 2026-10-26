#!/usr/bin/env python3
"""Queue 20 matched native-PAOS long workflows after the existing batches.

Each seed has two opposite priority histories.  Every history gets a private
oracle reachability run and one native PAOS run.  Capability failures are kept;
the scheduler never restarts a terminal case or gives the model oracle answers.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/data/stormlab/xi/paos/worktrees/native-long-workflow-v4b-20261006')
DEPLOY = Path('/data/stormlab/xi/paos/qwen-deploy')
RESULTS = Path('/data/stormlab/xi/paos/results')
PHYSICAL = RESULTS / 'native-memory-diagnostic-v2-20261005T161809Z'
ATOMIC = RESULTS / 'native-atomic-diagnostic-v3-20261005T175456Z'
SKILL = RESULTS / 'yellow-cup-skill-v1-20261005T171013Z'
PYTHON = '/home/xi/envs/agent/bin/python'
COMMIT = '58521c6166b3813dd0343a8b64f51abda3134f5b'
SOURCES = ('long_mission_contract.py', 'real_breakfast_worker.py',
           'run_breakfast.py', 'launch_breakfast.py')
CONDITIONS = ('butter_first', 'bowl_first')
CHECKPOINTS = ('nested_priority', 'session_resume_1', 'delayed_cleanup',
               'session_resume_2', 'replacement_decision')
SEEDS = tuple(range(20))


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def alive(identity_file):
    if not identity_file.exists():
        return False
    try:
        owner = json.loads(identity_file.read_text())
        fields = (Path('/proc') / str(owner['pid']) / 'stat').read_text().rsplit(') ', 1)[1].split()
        return fields[0] != 'Z' and int(fields[19]) == int(owner['start_ticks'])
    except (OSError, ValueError, KeyError, IndexError):
        return False


def dependencies(out):
    deadline = time.monotonic() + 7 * 24 * 3600
    while True:
        states = {}
        for name, root in (('physical_v2', PHYSICAL), ('atomic_v3', ATOMIC),
                           ('yellow_cup_skill', SKILL)):
            file = root / 'progress.json'
            states[name] = json.loads(file.read_text()).get('stage') if file.exists() else 'missing'
        # A dead skill probe must not block the next experiment forever.  Its
        # incomplete evidence remains recorded as a failed dependency.
        skill_dead = states['yellow_cup_skill'] != 'finished' and not alive(SKILL / 'probe-identity.json')
        ready = (states['physical_v2'] == 'finished' and
                 states['atomic_v3'] == 'finished' and
                 (states['yellow_cup_skill'] == 'finished' or skill_dead))
        save(out / 'dependency.json', {'states': states,
             'skill_probe_exited_incomplete': skill_dead, 'ready': ready})
        if ready:
            return states
        if time.monotonic() > deadline:
            raise TimeoutError('upstream_batches_not_terminal_after_seven_days')
        time.sleep(60)


def summarize(case, seed, condition, controller, gpu):
    file = case / 'episode/result.json'
    result = json.loads(file.read_text()) if file.exists() else {}
    contract = result.get('contract') or {}
    exit_file = case / 'exit-code.txt'
    return {
        'case': str(case), 'seed': seed, 'condition': condition,
        'controller': controller, 'gpu': gpu,
        'status': result.get('status', 'missing_result'),
        'exit_code': int(exit_file.read_text().strip()) if exit_file.exists() else None,
        'failure_domain': result.get('failure_domain'), 'reason': result.get('reason'),
        'oracle_reachable': (controller == 'oracle_reference' and
            result.get('status') == 'completed' and
            result.get('successful_moves') == 17 and
            result.get('failed_moves') == 0 and
            contract.get('terminal_facts_valid') is True),
        'mission_success': result.get('diagnostic_mission_success', False),
        'checkpoint_reached': contract.get('checkpoint_reached', 0),
        'checkpoint_correct': contract.get('checkpoint_correct', 0),
        'checkpoints': {k: (contract.get('checkpoints') or {}).get(k) for k in CHECKPOINTS},
        'session_switches': contract.get('session_switches'),
        'successful_moves': result.get('successful_moves'),
        'failed_moves': result.get('failed_moves'),
        'model_calls': result.get('model_calls'),
        'result': str(file) if result else None,
    }


def launch_or_attach(case, seed, condition, controller, gpu):
    if not case.exists():
        cmd = [PYTHON, str(ROOT / 'scripts/launch_breakfast.py'), 'launch',
               '--output', str(case), '--gpu', str(gpu), '--seed', str(seed),
               '--condition', condition, '--controller', controller,
               '--executor', 'diagnostic_atomic', '--policy-port', str(18981 + gpu),
               '--action-steps', '1000', '--max-steps', '36000',
               '--max-actions', '160', '--max-calls', '400',
               '--wall-seconds', '3600']
        launched = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                  text=True, check=True, timeout=120)
        if Path(json.loads(launched.stdout)['output']) != case:
            raise RuntimeError('launcher_output_mismatch')
    owner = case / 'launcher-identity.json'
    if not owner.exists():
        return {'case': str(case), 'seed': seed, 'condition': condition,
                'controller': controller, 'gpu': gpu,
                'status': 'launch_incomplete'}
    while not (case / 'exit-code.txt').exists():
        if not alive(owner):
            return {'case': str(case), 'seed': seed, 'condition': condition,
                    'controller': controller, 'gpu': gpu,
                    'status': 'launcher_lost'}
        time.sleep(5)
    return summarize(case, seed, condition, controller, gpu)


def progress(out, records, stage, active=None):
    paos = [r for r in records if r.get('controller') == 'paos']
    oracle = [r for r in records if r.get('controller') == 'oracle_reference']
    save(out / 'progress.json', {
        'stage': stage, 'planned_oracle_cases': 40, 'planned_native_cases': 40,
        'planned_total_cases': 80, 'terminal_oracle_cases': len(oracle),
        'terminal_native_cases': len(paos), 'terminal_total_cases': len(records),
        'planned_native_checkpoints': 200,
        'reached_native_checkpoints': sum(r.get('checkpoint_reached') or 0 for r in paos),
        'correct_native_checkpoints': sum(r.get('checkpoint_correct') or 0 for r in paos),
        'native_mission_success': sum(r.get('mission_success') is True for r in paos),
        'oracle_reachable': sum(r.get('oracle_reachable') is True for r in oracle),
        'active_cases': active or [], 'records': records,
        'manifest': str(out / 'manifest.json'),
    })


def run_pair(pool, out, seed, controller, records, known):
    futures = {}
    active = []
    for index, condition in enumerate(CONDITIONS):
        key = (seed, condition, controller)
        if key in known:
            continue
        gpu = (seed + index) % 2
        case = out / ('s%02d-%s-%s' % (seed, condition, controller))
        futures[key] = pool.submit(launch_or_attach, case, seed, condition,
                                   controller, gpu)
        active.append(str(case))
    if not futures:
        return
    progress(out, records, 'running', active)
    for key, future in futures.items():
        try:
            row = future.result()
        except Exception as exc:
            row = {'seed': key[0], 'condition': key[1],
                   'controller': key[2], 'status': 'batch_exception',
                   'exception_type': type(exc).__name__}
        records.append(row)
        known.add(key)
        progress(out, records, 'running', active)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: run_long_native_queue.py OUTPUT')
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                         cwd=ROOT, text=True).strip()
        if commit != COMMIT:
            raise RuntimeError('unexpected_worktree_commit')
        hashes = {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                  for name in SOURCES}
        manifest = {'protocol': 'native-paos-continuous-service-v4b',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'source_commit': commit, 'source_hashes': hashes,
                    'scheduler_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'controller': 'paos', 'oracle_for_reachability_only': True,
                    'conditions': CONDITIONS, 'seeds': SEEDS,
                    'planned_native_cases': 40, 'planned_oracle_cases': 40,
                    'planned_native_checkpoints': 200,
                    'expected_moves_per_oracle': 17,
                    'planned_session_switches_per_native_case': 2,
                    'executor': 'privileged_simulator_atomic_object_placement',
                    'physical_transport_claim': False,
                    'case_retry_policy': 'never rerun capability or model failures',
                    'waits_for': [str(PHYSICAL), str(ATOMIC), str(SKILL)],
                    'gpu_locks': ['robot-run.lock', 'gpt-gpu1-run.lock'],
                    'analysis': 'Report checkpoint coverage and correct/reached for native PAOS; oracle failures are reachability failures and never memory failures. The 17 moves are one continuous service-and-clearance workflow.'}
        file = out / 'manifest.json'
        if file.exists():
            old = json.loads(file.read_text())
            if old['source_commit'] != commit or old['source_hashes'] != hashes:
                raise RuntimeError('frozen_source_mismatch')
        else:
            save(file, manifest)
        (DEPLOY / 'latest-native-long-workflow-v4.txt').write_text(str(out) + '\n')
        old_progress = out / 'progress.json'
        records = json.loads(old_progress.read_text()).get('records', []) if old_progress.exists() else []
        known = {(r.get('seed'), r.get('condition'), r.get('controller')) for r in records}
        progress(out, records, 'waiting_for_existing_batches')
        dependencies(out)
        progress(out, records, 'running')
        with ThreadPoolExecutor(max_workers=2) as pool:
            for seed in SEEDS:
                run_pair(pool, out, seed, 'oracle_reference', records, known)
                if seed == 0:
                    first_oracles = [r for r in records
                                     if r.get('controller') == 'oracle_reference'
                                     and r.get('seed') == 0]
                    if (len(first_oracles) != 2 or
                            not all(r.get('oracle_reachable') is True
                                    for r in first_oracles)):
                        progress(out, records, 'qualification_failed')
                        save(out / 'qualification-failure.json', {
                            'reason': 'seed0_oracle_did_not_reach_all_17_moves',
                            'oracle_results': first_oracles,
                            'native_model_cases_started': 0,
                        })
                        return
                run_pair(pool, out, seed, 'paos', records, known)
        progress(out, records, 'finished')
        paos = [r for r in records if r.get('controller') == 'paos']
        oracle = [r for r in records if r.get('controller') == 'oracle_reference']
        save(out / 'final-report.json', {
            'source_commit': commit,
            'native_cases': len(paos), 'native_success': sum(r.get('mission_success') is True for r in paos),
            'oracle_cases': len(oracle), 'oracle_reachable': sum(r.get('oracle_reachable') is True for r in oracle),
            'checkpoint_planned': 200,
            'checkpoint_reached': sum(r.get('checkpoint_reached') or 0 for r in paos),
            'checkpoint_correct': sum(r.get('checkpoint_correct') or 0 for r in paos),
            'native_failure_domains': dict(Counter(r.get('failure_domain') for r in paos
                                                    if r.get('failure_domain'))),
            'oracle_failure_domains': dict(Counter(r.get('failure_domain') for r in oracle
                                                    if r.get('failure_domain'))),
            'interpretation': 'Atomic placement isolates high-level decisions; qualification, reached checkpoints, and physical transport remain separate evidence.'
        })


if __name__ == '__main__':
    main()
