"""One explicitly leased GPU policy, owned by a persistent systemd user service.

No experiment runner, retries, method edits, or checkpoint changes are performed.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def identity(pid):
    return {'pid': pid, 'start_ticks': Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()[19],
            'pgid': os.getpgid(pid)}


def same_process(record):
    try:
        return identity(record['pid'])['start_ticks'] == record['start_ticks']
    except (FileNotFoundError, ProcessLookupError):
        return False


def reachable(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--core', required=True)
    parser.add_argument('--gpu', type=int, required=True)
    parser.add_argument('--startup-timeout', type=float, default=900)
    args = parser.parse_args()
    if args.gpu not in (2, 3, 4, 6, 7):
        parser.error('only the five authorized GPU lanes are allowed')
    root, source, core = Path(args.root), Path(args.source), Path(args.core)
    runtime = root / 'code/runtime'
    sys.path.insert(0, str(runtime))
    from libero_runtime import Paths, lane_env, policy_command
    os.environ.update(PAOS_LIBERO_SOURCE=str(source), PAOS_CORE_ROOT=str(core))
    paths = Paths()
    paths.validate()
    port = 20500 + args.gpu
    unit = 'paos-libero-rsi-policy-gpu%d.service' % args.gpu
    output = root / 'policy-services' / ('gpu%d' % args.gpu)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'identity.json').exists():
        raise RuntimeError('policy_service_already_registered_no_automatic_restart')
    source_hashes = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                     for name in ('serve_paired_policy.py', 'paired_sampling.py',
                                  'native_world.py', 'retry_recovery.py')}
    source_hash = hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest()
    shared = dict(gpu=args.gpu, port=port, unit=unit, source=str(source), core=str(core),
                  source_sha256=source_hash, source_files_sha256=source_hashes,
                  checkpoint=str(paths.checkpoint), supervisor=identity(os.getpid()),
                  automatic_retry=False, physics_requests_started=0)
    process, child, lease = None, None, None
    stop_signal = None
    was_ready = False

    def status(state, **fields):
        record = dict(shared, state=state, updated_unix=time.time(), **fields)
        atomic_json(output / 'status.json', record)
        with (output / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
        print(json.dumps(record, sort_keys=True), flush=True)

    def request_stop(signum, _frame):
        nonlocal stop_signal
        stop_signal = signum

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    def stop_owned():
        if process is not None and process.poll() is None and child is not None and same_process(child):
            os.killpg(child['pgid'], signal.SIGTERM)
            try:
                process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                if same_process(child):
                    os.killpg(child['pgid'], signal.SIGKILL)
                process.wait(timeout=10)

    try:
        lease_path = paths.migration / 'portable-runtime-20261023/paos/qwen-deploy' / ('gpt-gpu%d-run.lock' % args.gpu)
        lease = lease_path.open('a')
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        used = int(subprocess.check_output(['nvidia-smi', '-i', str(args.gpu), '--query-gpu=memory.used',
                                           '--format=csv,noheader,nounits'], text=True).strip())
        if used >= 1024:
            raise RuntimeError('gpu_busy_%dMiB' % used)
        if reachable(port):
            raise RuntimeError('policy_port_already_in_use')
        if stop_signal is not None:
            status('stopped_before_start', received_signal=stop_signal)
            return 0
        command = policy_command(port)
        with (output / 'policy.log').open('xb') as log:
            process = subprocess.Popen(command, env=lane_env(args.gpu, 'policy'),
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True)
        child = identity(process.pid)
        shared.update(policy=child, command=command, lease_path=str(lease_path),
                      gpu_memory_before_mib=used)
        atomic_json(output / 'identity.json', shared)
        status('starting', startup_timeout_seconds=args.startup_timeout)
        started = time.monotonic()
        while True:
            if stop_signal is not None:
                status('stopping', received_signal=stop_signal)
                stop_owned()
                status('stopped', received_signal=stop_signal, policy_returncode=process.returncode)
                return 0
            returncode = process.poll()
            if returncode is not None:
                status('failed', reason='policy_exited_after_ready' if was_ready else 'policy_exited_during_startup',
                       policy_returncode=returncode,
                       policy_exit_signal=-returncode if returncode < 0 else None)
                return 1
            if not was_ready:
                if reachable(port):
                    was_ready = True
                    status('ready', startup_elapsed_seconds=time.monotonic() - started)
                elif time.monotonic() - started >= args.startup_timeout:
                    status('failed', reason='policy_startup_timeout', startup_timeout_seconds=args.startup_timeout,
                           policy_returncode=None)
                    return 1
            time.sleep(1)
    except BaseException as error:
        status('failed', reason=str(error), error_type=type(error).__name__,
               policy_returncode=process.poll() if process is not None else None,
               received_signal=stop_signal)
        return 1
    finally:
        stop_owned()
        if lease is not None:
            lease.close()


if __name__ == '__main__':
    raise SystemExit(main())
