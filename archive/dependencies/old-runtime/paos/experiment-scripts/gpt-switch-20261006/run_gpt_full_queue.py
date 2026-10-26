#!/usr/bin/env python3
"""Run the frozen PAOS v6 full workflow with the existing local GPT gateway.

This is a new model cohort. It never incorporates or overwrites Qwen results.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock
import time
from urllib.request import urlopen


ROOT = Path('/data/stormlab/xi/paos/worktrees/native-long-workflow-v6-gpt-20261006')
DEPLOY = Path('/data/stormlab/xi/paos/qwen-deploy')
PYTHON = '/home/xi/envs/agent/bin/python'
MODEL = 'gpt-5.6-luna'
GPUS = (0, 1, 3, 5)
SEEDS = tuple(range(20))
CONDITIONS = ('front_butter_final', 'rear_butter_final')


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def alive(path):
    try:
        row = json.loads(path.read_text())
        fields = (Path('/proc') / str(row['pid']) / 'stat').read_text().rsplit(') ', 1)[1].split()
        return fields[0] != 'Z' and int(fields[19]) == int(row['start_ticks'])
    except (OSError, KeyError, ValueError, IndexError):
        return False


def gateway_ok():
    try:
        with urlopen('http://127.0.0.1:19080/health', timeout=3) as reply:
            data = json.load(reply)
        return data.get('ok') is True and data.get('model') == MODEL
    except Exception:
        return False


def case_id(seed, condition):
    return f's{seed:02d}-{condition}-gpt-full'


def run_case(out, seed, condition, gpu):
    case = out / case_id(seed, condition)
    if not case.exists():
        command = [PYTHON, str(ROOT / 'scripts/launch_breakfast.py'), 'launch',
                   '--output', str(case), '--gpu', str(gpu), '--seed', str(seed),
                   '--condition', condition, '--controller', 'paos', '--mode', 'full',
                   '--cue', 'hidden', '--executor', 'diagnostic_atomic',
                   '--api-base', 'http://127.0.0.1:19080/v1',
                   '--api-key-file', str(DEPLOY / 'gpt-gateway-token'),
                   '--model', MODEL, '--policy-port', str(19320 + gpu),
                   '--action-steps', '1000', '--max-steps', '36000',
                   '--max-actions', '160', '--max-calls', '500', '--wall-seconds', '5400']
        launched = subprocess.run(command, cwd=ROOT, capture_output=True,
                                  text=True, check=True, timeout=120)
        if Path(json.loads(launched.stdout)['output']) != case:
            raise RuntimeError('launcher_output_mismatch')
    owner = case / 'launcher-identity.json'
    while not (case / 'exit-code.txt').exists():
        if not owner.exists() or not alive(owner):
            return {'case_id': case.name, 'seed': seed, 'condition': condition,
                    'gpu': gpu, 'status': 'launcher_lost'}
        time.sleep(5)
    result_file = case / 'episode/result.json'
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    contract = result.get('contract') or {}
    return {'case_id': case.name, 'case': str(case), 'seed': seed,
            'condition': condition, 'gpu': gpu,
            'status': result.get('status', 'missing_result'),
            'failure_domain': result.get('failure_domain'),
            'reason': result.get('reason'),
            'mission_success': result.get('mission_success'),
            'horizon_qualified': result.get('horizon_qualified'),
            'checkpoint_reached': contract.get('checkpoint_reached'),
            'checkpoint_correct': contract.get('checkpoint_correct'),
            'session_switches': contract.get('session_switches'),
            'result': str(result_file) if result else None}


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: run_gpt_full_queue.py OUTPUT')
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sources = {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                   for name in ('long_mission_contract.py', 'run_breakfast.py',
                                'real_breakfast_worker.py', 'launch_breakfast.py')}
        manifest = {'protocol': 'native-paos-v6-gpt-full-model-switch',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'source_commit': subprocess.check_output(
                        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    'source_hashes': sources,
                    'scheduler_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'model': MODEL, 'gateway': 'local SIWC Responses gateway',
                    'executor': 'diagnostic_atomic', 'physical_transport_claim': False,
                    'gpus': GPUS, 'seeds': SEEDS, 'conditions': CONDITIONS,
                    'planned': len(SEEDS) * len(CONDITIONS),
                    'case_retry_policy': 'no automatic retry of terminal cases',
                    'prior_qwen_cohort': '/data/stormlab/xi/paos/results/native-long-workflow-v6-20261006T064828Z',
                    'comparison_rule': 'Do not pool GPT and Qwen outcomes.'}
        manifest_file = out / 'manifest.json'
        if manifest_file.exists():
            old = json.loads(manifest_file.read_text())
            if old['source_hashes'] != sources or old['scheduler_sha256'] != manifest['scheduler_sha256']:
                raise RuntimeError('frozen_source_mismatch')
        else:
            save(manifest_file, manifest)
        (DEPLOY / 'latest-native-long-workflow-v6-gpt-full.txt').write_text(str(out) + '\n')
        progress_file = out / 'progress.json'
        records = json.loads(progress_file.read_text()).get('records', []) if progress_file.exists() else []
        known = {row['case_id'] for row in records}
        guard = Lock()
        active = set()

        def snapshot(stage):
            save(progress_file, {
                'stage': stage, 'planned': manifest['planned'],
                'terminal': len(records), 'active_cases': sorted(active),
                'mission_success': sum(r.get('mission_success') is True for r in records),
                'horizon_qualified': sum(r.get('horizon_qualified') is True for r in records),
                'failure_domains': dict(Counter(r.get('failure_domain') for r in records
                                                if r.get('failure_domain'))),
                'records': records})

        if not gateway_ok():
            snapshot('gateway_unavailable')
            return 2
        todo = [(seed, condition) for seed in SEEDS for condition in CONDITIONS
                if case_id(seed, condition) not in known]

        def worker(index, gpu):
            for seed, condition in todo[index::len(GPUS)]:
                key = case_id(seed, condition)
                with guard:
                    active.add(key)
                    snapshot('running')
                try:
                    row = run_case(out, seed, condition, gpu)
                except Exception as exc:
                    row = {'case_id': key, 'seed': seed, 'condition': condition,
                           'gpu': gpu, 'status': 'batch_exception',
                           'exception_type': type(exc).__name__}
                with guard:
                    active.remove(key)
                    records.append(row)
                    snapshot('running')

        snapshot('running')
        with ThreadPoolExecutor(max_workers=len(GPUS)) as pool:
            futures = [pool.submit(worker, i, gpu) for i, gpu in enumerate(GPUS)]
            for future in futures:
                future.result()
        snapshot('finished')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
