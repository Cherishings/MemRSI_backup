#!/usr/bin/env python3
"""Continue missing worker-1 v3 trials without changing the original run or code.

One subprocess group per attempt bounds runtime and keeps cleanup scoped to this
continuation. The caller owns GPU allocation and policy startup/shutdown.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace


OWNED_ATTEMPTS = []


def interrupted(signum, frame):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise InterruptedError("Continuation interrupted by signal {}".format(signum))


def start_attempt(command, log):
    # Block termination across fork/registration so a signal cannot strand an
    # unregistered session between Popen returning and ownership registration.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    try:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        OWNED_ATTEMPTS.append(process)
        return process
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(str(temp), str(path))


def identity(pid):
    try:
        stat = Path('/proc/{}/stat'.format(pid)).read_text()
        fields = stat[stat.rindex(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return {'pid': int(pid), 'start_ticks': fields[19],
                'command_sha256': digest('/proc/{}/cmdline'.format(pid))}
    except (OSError, ValueError, IndexError):
        return None


def known_transport(result, requests_path=None):
    if result.get('status') != 'error':
        return False
    error_type = result.get('error_type', '')
    error = str(result.get('error', ''))
    last_response = {}
    if requests_path and Path(requests_path).exists():
        for line in Path(requests_path).read_text().splitlines():
            if line.strip():
                last_response = json.loads(line).get('response') or {}
    explicit_response = (last_response.get('finish_reason') == 'error' and
        any(marker in str(last_response.get('content', '')) for marker in
            ('Request timed out', 'Connection error', 'connection refused', 'Connection refused')))
    return (explicit_response or error_type in {'APITimeoutError', 'APIConnectionError', 'ConnectTimeout', 'ReadTimeout'}
            or 'transport_failure:APITimeoutError' in error
            or 'transport_failure:APIConnectionError' in error)


def terminal(result):
    return bool(result and result.get('status') in {'completed', 'model_failure', 'task_failure'})


def verify_sources(manifest, original, original_hash):
    if digest(Path(original) / 'manifest.json') != original_hash:
        raise RuntimeError('Original manifest changed')
    for path, expected in manifest['sources'].items():
        if digest(path) != expected:
            raise RuntimeError('Frozen source changed: ' + path)


def original_args(manifest, cli, output):
    budgets = manifest['budgets']
    # These are the original v3 CLI defaults. The manifest overrides all
    # evaluation budgets; provider_timeout_s is intentionally absent (120 s).
    return SimpleNamespace(output=str(output), worker=cli.worker,
        runtime_file=cli.runtime_file, policy_port=cli.policy_port,
        api_key_file=cli.api_key_file, libero_python=cli.libero_python,
        api_base='http://127.0.0.1:18080/v1', model='Qwen/Qwen3.8-27B',
        max_calls=budgets['model_calls_per_case'], context_window=24000,
        max_iterations=8, max_skills=budgets['max_skills'],
        skill_steps=budgets['skill_steps'], total_steps=budgets['total_steps'],
        rollover_after_skills=budgets['rollover_after_skills'])


def selected_jobs(manifest, original, worker):
    selected, skipped, blocked = [], [], []
    for i, case in enumerate(manifest['jobs']):
        if i % 2 != worker:
            continue
        folder = Path(original) / 'cases' / case['id']
        result_file = folder / 'result.json'
        result = json.loads(result_file.read_text()) if result_file.exists() else None
        if terminal(result):
            skipped.append(case['id'])
        elif result is None or known_transport(result, folder / 'requests.jsonl'):
            selected.append({'case': case, 'source_case': str(folder),
                             'original_attempts': int(folder.exists()), 'original_result': result})
        else:
            blocked.append({'case': case['id'], 'reason': 'unknown original infrastructure failure',
                            'source_case': str(folder)})
    selected.sort(key=lambda j: j['original_result'] is not None)
    return selected, skipped, blocked


def same_identity(actual, expected):
    return bool(actual and expected and int(actual['pid']) == int(expected['pid'])
                and str(actual['start_ticks']) == str(expected['start_ticks']))


def verify_policy(pid, expected, port):
    if not same_identity(identity(pid), expected):
        raise RuntimeError('Owned policy exited or PID identity changed')
    command = Path('/proc/{}/cmdline'.format(pid)).read_bytes().replace(b'\0', b' ').decode()
    if 'serve_mission_policy.py' not in command:
        raise RuntimeError('Policy PID is not the expected serving script')
    env = dict(part.split(b'=', 1) for part in Path('/proc/{}/environ'.format(pid)).read_bytes().split(b'\0') if b'=' in part)
    if env.get(b'PAOS_DIAG_PORT') != str(port).encode():
        raise RuntimeError('Policy port ownership does not match')


def wait_lane(cli, policy):
    if not cli.original_parent_pid:
        return
    expected = json.loads(Path(cli.original_parent_identity_file).read_text())
    if int(expected['pid']) != cli.original_parent_pid:
        raise RuntimeError('Original-parent PID does not match its identity record')
    while True:
        verify_policy(cli.policy_pid, policy, cli.policy_port)
        if same_identity(identity(cli.original_parent_pid), expected):
            return
        lease = Path(cli.lease_acquired_file)
        if lease.exists():
            row = json.loads(lease.read_text())
            holder = row.get('holder')
            if row.get('acquired') and holder and same_identity(identity(holder['pid']), holder):
                return
        time.sleep(2)


def redact(value, key):
    if isinstance(value, str):
        return value.replace(key, '[REDACTED]') if key else value
    if isinstance(value, dict):
        return {k: redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    return value


def stop_owned_group(process):
    # This process group was created with start_new_session=True below.
    if process in OWNED_ATTEMPTS:
        OWNED_ATTEMPTS.remove(process)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)
    # A child may outlive its group leader; no other task shares this group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def child_trial(cli):
    manifest = json.loads((Path(cli.original) / 'manifest.json').read_text())
    verify_sources(manifest, cli.original, cli.manifest_hash)
    repo = Path(cli.repo).resolve()
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / 'scripts'))
    spec = importlib.util.spec_from_file_location('original_v3_trial', repo / 'scripts' / 'run_continuous_mission.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, diagnose=False, backtrace=False)
    case = json.loads(Path(cli.case_json).read_text())
    output = Path(cli.attempt_output)
    args = original_args(manifest, cli, output)
    key = Path(cli.api_key_file).read_text().strip()
    await module.trial(args, case, output, key)


def run(cli):
    os.umask(0o077)
    original, output = Path(cli.original).resolve(), Path(cli.output).resolve()
    if original == output or original in output.parents:
        raise ValueError('Continuation output must be outside the original run')
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = original / 'manifest.json'
    manifest_hash = digest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    verify_sources(manifest, original, manifest_hash)
    jobs, skipped, blocked = selected_jobs(manifest, original, cli.worker)
    policy = identity(cli.policy_pid)
    if not policy:
        raise RuntimeError('Owned policy process is absent')
    verify_policy(cli.policy_pid, policy, cli.policy_port)
    key = Path(cli.api_key_file).read_text().strip()
    meta = {'original': str(original), 'repo': str(Path(cli.repo).resolve()),
            'manifest_sha256': manifest_hash, 'sources': manifest['sources'],
            'source_worker': cli.worker, 'policy': policy, 'policy_port': cli.policy_port,
            'process_identity': identity(os.getpid()), 'continuation_script_sha256': digest(__file__),
            'case_timeout_seconds': cli.case_timeout, 'max_total_attempts': 3,
            'scheduled': [j['case']['id'] for j in jobs], 'skipped_terminal': skipped,
            'blocked_original_cases': blocked,
            'original_evaluation_args': vars(original_args(manifest, cli, output)),
            'note': 'Original completed/model/task failures are never rerun; only missing or explicit transport failures continue.'}
    write_json(output / 'continuation-meta.json', meta)
    progress = {'status': 'running', 'planned': len(jobs), 'finished': 0, 'cases': {},
                'process_identity': meta['process_identity'], 'original': str(original)}
    write_json(output / 'progress.json', progress)
    overall = 2 if blocked else 0
    for job in jobs:
        case = job['case']
        case_dir = output / 'attempts' / case['id']
        case_dir.mkdir(parents=True, exist_ok=True)
        write_json(case_dir / 'case.json', case)
        record = {'source_case': job['source_case'], 'original_attempts': job['original_attempts'],
                  'attempts': [], 'status': 'pending'}
        progress['cases'][case['id']] = record
        stop_queue = False
        previous = sorted(case_dir.glob('attempt-*'))
        for path in previous:
            result_file = path / 'cases' / case['id'] / 'result.json'
            result = json.loads(result_file.read_text()) if result_file.exists() else None
            record['attempts'].append({'directory': str(path), 'result': redact(result, key), 'recovered': True})
        if record['attempts'] and terminal(record['attempts'][-1]['result']):
            record['status'] = 'terminal'
        elif record['attempts'] and not known_transport(record['attempts'][-1]['result'],
                Path(record['attempts'][-1]['directory']) / 'cases' / case['id'] / 'requests.jsonl'):
            record.update(status='blocked', reason='Previous unknown infrastructure failure retained')
            stop_queue = True
        else:
            used = job['original_attempts'] + len(record['attempts'])
            while used < 3:
                verify_sources(manifest, original, manifest_hash)
                wait_lane(cli, policy)
                verify_policy(cli.policy_pid, policy, cli.policy_port)
                if identity(cli.policy_pid) != policy:
                    record.update(status='blocked', reason='Owned policy exited or PID identity changed')
                    stop_queue = True
                    break
                used += 1
                attempt = case_dir / ('attempt-{:02d}'.format(used))
                attempt.mkdir(exist_ok=False)
                command = [sys.executable, str(Path(__file__).resolve()), '--original', str(original),
                    '--repo', cli.repo, '--output', str(output), '--worker', str(cli.worker),
                    '--policy-port', str(cli.policy_port), '--policy-pid', str(cli.policy_pid),
                    '--api-key-file', cli.api_key_file, '--runtime-file', cli.runtime_file,
                    '--libero-python', cli.libero_python, '--child', '--case-json', str(case_dir / 'case.json'),
                    '--attempt-output', str(attempt), '--manifest-hash', manifest_hash]
                with (attempt / 'trial.log').open('w') as log:
                    process = start_attempt(command, log)
                    row = {'directory': str(attempt), 'attempt_number_including_original': used,
                           'process_identity': identity(process.pid), 'started_at': time.time()}
                    record['attempts'].append(row)
                    record['status'] = 'running'
                    write_json(output / 'progress.json', progress)
                    timed_out = False
                    try:
                        process.wait(timeout=cli.case_timeout)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        stop_owned_group(process)
                    except BaseException:
                        stop_owned_group(process)
                        raise
                    finally:
                        stop_owned_group(process)
                    result_path = attempt / 'cases' / case['id'] / 'result.json'
                    result = json.loads(result_path.read_text()) if result_path.exists() else None
                    row.update(returncode=process.returncode, timed_out=timed_out,
                               result=redact(result, key), finished_at=time.time())
                if terminal(result):
                    record['status'] = 'terminal'
                    break
                if timed_out or not result or not known_transport(result, result_path.parent / 'requests.jsonl') or identity(cli.policy_pid) != policy:
                    record.update(status='blocked', reason='Unknown infrastructure failure or policy death; remaining cases retained')
                    stop_queue = True
                    break
                record['status'] = 'retrying_transport' if used < 3 else 'infrastructure_exhausted'
                write_json(output / 'progress.json', progress)
            if used >= 3 and record['status'] == 'pending':
                record['status'] = 'infrastructure_exhausted'
        if record['status'] == 'terminal':
            progress['finished'] += 1
        else:
            overall = 2
        write_json(output / 'progress.json', progress)
        if stop_queue:
            break
    progress['status'] = 'completed' if overall == 0 else 'incomplete'
    progress['exit_code'] = overall
    write_json(output / 'progress.json', progress)
    (output / 'exit-code.txt').write_text(str(overall) + '\n')
    return overall


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', required=True)
    p.add_argument('--repo', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--worker', type=int, choices=[1], required=True)
    p.add_argument('--policy-port', type=int, required=True)
    p.add_argument('--policy-pid', type=int, required=True)
    p.add_argument('--api-key-file', default='/data/stormlab/xi/paos/qwen-deploy/api-key')
    p.add_argument('--runtime-file', default='/data/stormlab/xi/paos/results/memory-gap-20261001T070849Z/code/vendor/libero_server.py')
    p.add_argument('--libero-python', default='/data/stormlab/xi/paos/venvs/libero/bin/python')
    p.add_argument('--original-parent-pid', type=int)
    p.add_argument('--original-parent-identity-file')
    p.add_argument('--lease-acquired-file')
    p.add_argument('--case-timeout', type=float, default=14400)
    p.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--case-json', help=argparse.SUPPRESS)
    p.add_argument('--attempt-output', help=argparse.SUPPRESS)
    p.add_argument('--manifest-hash', help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.original_parent_pid and not (args.original_parent_identity_file and args.lease_acquired_file):
        p.error('original-parent-pid requires identity and lease files')
    if not 0 < args.case_timeout <= 14400:
        p.error('case-timeout must be positive and at most four hours')
    return args


if __name__ == '__main__':
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM, signal.SIGINT})
    os.umask(0o077)
    args = parse_args()
    if args.child:
        asyncio.run(child_trial(args))
    else:
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            code = run(args)
        except BaseException as exc:
            target = Path(args.output)
            target.mkdir(parents=True, exist_ok=True)
            write_json(target / 'fatal.json', {'error_type': type(exc).__name__, 'error': str(exc),
                                             'process_identity': identity(os.getpid())})
            (target / 'exit-code.txt').write_text('2\n')
            code = 2
        finally:
            # Also covers a signal arriving after registration but before the
            # per-attempt wait/try block. The policy and lease are caller-owned.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            for process in list(OWNED_ATTEMPTS):
                stop_owned_group(process)
        sys.exit(code)
