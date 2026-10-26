#!/usr/bin/env python3
"""Continue the frozen atomic diagnostic with native PAOS only.

The two seed-0 native cases in the superseded v3 queue remain valid and are
linked, never rerun. This queue schedules seeds 1..19, both priority histories,
under the same committed code, executor, budgets, and shared GPU locks.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path('/data/stormlab/xi/paos/worktrees/native-memory-diagnostic-v3-20261006')
PREVIOUS = Path('/data/stormlab/xi/paos/results/dual-executor-diagnostic-v3-20261005T170546Z')
DEPLOY = Path('/data/stormlab/xi/paos/qwen-deploy')
PYTHON = '/home/xi/envs/agent/bin/python'
SEEDS = tuple(range(1, 20))
CONDITIONS = ('butter_first', 'bowl_first')
CHECKPOINTS = ('priority_decision', 'session_resume',
               'post_revision_decision', 'replacement_decision')
SOURCES = ('mission_breakfast_contract.py', 'launch_breakfast.py',
           'run_breakfast.py', 'real_breakfast_worker.py')


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def identity(pid):
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
        return int(fields[19])
    except (OSError, IndexError, ValueError):
        return None


def summarize(case, seed, condition, gpu):
    result_file = case / 'episode/result.json'
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    contract = result.get('contract') or {}
    exit_file = case / 'exit-code.txt'
    return {'case': str(case), 'seed': seed, 'condition': condition,
            'controller': 'paos', 'gpu': gpu,
            'status': result.get('status', 'missing_result'),
            'exit_code': int(exit_file.read_text().strip()) if exit_file.exists() else None,
            'failure_domain': result.get('failure_domain'),
            'reason': result.get('reason'),
            'checkpoint_reached': contract.get('checkpoint_reached', 0),
            'checkpoint_correct': contract.get('checkpoint_correct', 0),
            'checkpoints': {name: (contract.get('checkpoints') or {}).get(name)
                            for name in CHECKPOINTS},
            'atomic_transitions': result.get('successful_moves'),
            'atomic_failures': result.get('failed_moves'),
            'diagnostic_mission_success': result.get('diagnostic_mission_success', False),
            'result': str(result_file) if result else None}


def launch_or_attach(case, seed, condition, gpu):
    if not case.exists():
        cmd = [PYTHON, str(ROOT / 'scripts/launch_breakfast.py'), 'launch',
               '--output', str(case), '--gpu', str(gpu), '--seed', str(seed),
               '--condition', condition, '--controller', 'paos',
               '--executor', 'diagnostic_atomic', '--policy-port', str(18971 + gpu),
               '--action-steps', '1000', '--max-steps', '36000',
               '--max-actions', '160', '--max-calls', '400',
               '--wall-seconds', '3600']
        launched = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                  timeout=120, check=True)
        if Path(json.loads(launched.stdout)['output']) != case:
            raise RuntimeError('launcher_output_mismatch')
    owner_file = case / 'launcher-identity.json'
    if not owner_file.exists():
        return {'case': str(case), 'seed': seed, 'condition': condition,
                'controller': 'paos', 'gpu': gpu, 'status': 'launch_incomplete'}
    owner = json.loads(owner_file.read_text())
    while True:
        if (case / 'exit-code.txt').exists():
            return summarize(case, seed, condition, gpu)
        if identity(owner['pid']) != int(owner['start_ticks']):
            return {'case': str(case), 'seed': seed, 'condition': condition,
                    'controller': 'paos', 'gpu': gpu, 'status': 'launcher_lost'}
        time.sleep(5)


def check_prior():
    prior = []
    for condition in CONDITIONS:
        oracle = PREVIOUS / ('qualification-' + condition) / 'episode/result.json'
        x = json.loads(oracle.read_text())
        if (x.get('status') != 'completed' or x.get('successful_moves') != 8
                or x.get('failed_moves') != 0 or
                (x.get('contract') or {}).get('terminal_facts_valid') is not True):
            raise RuntimeError('atomic_executor_prior_qualification_failed')
        case = PREVIOUS / ('s00-%s-paos' % condition)
        if not (case / 'exit-code.txt').exists():
            raise RuntimeError('prior_native_case_not_terminal')
        prior.append(summarize(case, 0, condition, CONDITIONS.index(condition)))
    return prior


def progress(out, records, stage, active=None):
    save(out / 'progress.json', {
        'stage': stage, 'planned_cases': 40, 'terminal_cases': len(records),
        'planned_checkpoints': 160,
        'reached_checkpoints': sum(r.get('checkpoint_reached', 0) for r in records),
        'correct_checkpoints': sum(r.get('checkpoint_correct', 0) for r in records),
        'active_cases': active or [], 'records': records,
        'manifest': str(out / 'manifest.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    out = Path(parser.parse_args().output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'queue.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('native queue already active')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                         text=True).strip()
        if commit != '6059f28b414534fcfd3fbac2cefa4a918157c125':
            raise RuntimeError('unexpected_frozen_commit')
        hashes = {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                  for name in SOURCES}
        prior = check_prior()
        manifest = {'protocol': 'native-paos-atomic-memory-diagnostic-v3',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'source_commit': commit, 'source_hashes': hashes,
                    'scheduler_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'controller': 'paos', 'retired_controller': 'paos_task_memory',
                    'executor': 'privileged_simulator_atomic_object_placement',
                    'prior_seed0_cases': [r['case'] for r in prior],
                    'seeds_new': SEEDS, 'conditions': CONDITIONS,
                    'planned_cases_total': 40, 'new_cases': 38,
                    'planned_checkpoints': 160,
                    'physical_comparison': '/data/stormlab/xi/paos/results/native-memory-diagnostic-v2-20261005T161809Z',
                    'retry_policy': 'no whole-case retries; no automatic capability retries',
                    'gpu_locks': ['robot-run.lock', 'gpt-gpu1-run.lock'],
                    'analysis': 'Native PAOS only. Report planned, reached, correct/reached for four checkpoints, plus full diagnostic completion and failure domains. Atomic placement is not physical transport.'}
        manifest_file = out / 'manifest.json'
        if manifest_file.exists():
            old = json.loads(manifest_file.read_text())
            if old['source_commit'] != commit or old['source_hashes'] != hashes:
                raise RuntimeError('frozen_source_mismatch')
        else:
            save(manifest_file, manifest)
        (DEPLOY / 'latest-native-atomic-diagnostic-v3.txt').write_text(str(out) + '\n')
        old_progress = out / 'progress.json'
        records = json.loads(old_progress.read_text()).get('records', []) if old_progress.exists() else prior
        known = {(r.get('seed'), r.get('condition')) for r in records}
        progress(out, records, 'running')
        with ThreadPoolExecutor(max_workers=2) as pool:
            for seed in SEEDS:
                futures = {}
                active = []
                for index, condition in enumerate(CONDITIONS):
                    key = (seed, condition)
                    if key in known:
                        continue
                    gpu = (seed + index) % 2
                    case = out / ('s%02d-%s-paos' % key)
                    futures[key] = pool.submit(launch_or_attach, case, seed,
                                                condition, gpu)
                    active.append(str(case))
                if not futures:
                    continue
                progress(out, records, 'running', active)
                for key, future in futures.items():
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = {'seed': key[0], 'condition': key[1],
                               'controller': 'paos', 'status': 'batch_exception',
                               'exception_type': type(exc).__name__}
                    records.append(row)
                    known.add(key)
                    progress(out, records, 'running', active)
        progress(out, records, 'finished')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
