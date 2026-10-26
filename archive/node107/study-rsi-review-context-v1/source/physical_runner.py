"""Own explicitly selected GPU policies only, after the existing standard leases are released.

No old ledger/evolution code is imported. A queue never kills a process it did
not start, and refuses a busy GPU/port even if a non-cooperating user has it.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import urllib.request

from run_queue import ROOT, BASE, dump, env, identity, ready, stop_group

PORTS = {gpu: 20500 + gpu for gpu in range(8)}
LOCKS = {gpu: ('robot-run.lock' if gpu == 0 else f'gpt-gpu{gpu}-run.lock') for gpu in range(8)}
AGENT_PYTHON = '/home/xi/envs/agent/bin/python'


def same_process(record):
    try:
        return identity(record['pid'])['start_ticks'] == str(record['start_ticks'])
    except (FileNotFoundError, ProcessLookupError):
        return False


def wait_for_policy(path, deadline, stop, progress):
    """Only a complete JSON file is accepted; learning writes it atomically."""
    from memory_policy import load
    path = Path(path)
    while True:
        if (path.parent / 'failure.json').exists():
            raise RuntimeError('evolution_failed')
        if path.is_file():
            # Validate the exact policy schema before launching any evolved run.
            return load(path)
        if stop.is_set():
            raise RuntimeError('queue_cancelled')
        if time.monotonic() >= deadline:
            raise RuntimeError('evolution_wait_budget_exhausted')
        progress('waiting_for_evolution', policy_path=str(path))
        stop.wait(10)


class PhysicalRunner:
    def __init__(self, output, stop=None, gpus=(0,1,6,7)):
        self.gpus = tuple(gpus)
        self.out = Path(output)
        self.stop = stop or threading.Event()
        self.locks = []
        self.processes = {}
        self.process_lock = threading.Lock()

    def track(self, process, kind):
        record = identity(process.pid)
        with self.process_lock:
            self.processes[process.pid] = (process, record, kind)
        return record

    def release_process(self, process):
        with self.process_lock:
            self.processes.pop(process.pid, None)

    def stop_owned(self, process):
        with self.process_lock:
            item = self.processes.get(process.pid)
        if item and process.poll() is None and same_process(item[1]):
            stop_group(process)

    def acquire(self, progress, wait_seconds=12 * 3600):
        deadline = time.monotonic() + wait_seconds
        # Acquire all selected leases before any policy load. No GPU is occupied while
        # waiting for the other one; no separate GPU allocation is attempted.
        while len(self.locks) != len(self.gpus):
            acquired = []
            for gpu in self.gpus:
                handle = (BASE / 'qwen-deploy' / LOCKS[gpu]).open('a')
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired.append(handle)
                except BlockingIOError:
                    handle.close()
                    break
            if len(acquired) == len(self.gpus):
                self.locks = acquired
                break
            for handle in acquired:
                handle.close()
            if self.stop.is_set():
                raise RuntimeError('queue_cancelled')
            if time.monotonic() >= deadline:
                raise RuntimeError('gpu_lock_wait_budget_exhausted')
            progress('waiting_for_previous_gpu_lease', gpus=list(self.gpus))
            self.stop.wait(10)
        for gpu in self.gpus:
            if ready(PORTS[gpu]):
                raise RuntimeError('reserved_policy_port_busy')
            used = int(subprocess.check_output([
                'nvidia-smi', '-i', str(gpu), '--query-gpu=memory.used',
                '--format=csv,noheader,nounits'], text=True).strip())
            if used > 1024:
                raise RuntimeError('gpu_busy_without_standard_lease')
        # Read no authorization material here. The provider uses the remote token.
        while True:
            if self.stop.is_set():raise RuntimeError('queue_cancelled')
            try:
                with urllib.request.urlopen('http://127.0.0.1:19099/health', timeout=15) as response:
                    health = json.load(response)
                break
            except (OSError,ValueError):
                progress('waiting_gateway_no_trial_started');self.stop.wait(10)
        if health.get('model') != 'gpt-5.6-luna' or health.get('gateway_version') != 'memory-v3-tool-choice':
            raise RuntimeError('gateway_model_mismatch')
        dump(self.out / 'gateway-health.json', {
            key: health.get(key) for key in
            ('model', 'gateway_version', 'transport_revision', 'max_output_tokens')})
        for gpu in self.gpus:
            with (self.out / f'policy-gpu{gpu}.log').open('xb') as log:
                p = subprocess.Popen([
                    str(BASE / 'venvs/policy/bin/python'),
                    str(ROOT / 'serve_paired_policy.py'), '--port', str(PORTS[gpu]),
                    '--checkpoint', str(BASE / 'models/pi05_libero')],
                    cwd='/data/stormlab/xi/openpi', env=env(gpu),
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True)
            record = self.track(p, 'policy')
            dump(self.out / f'policy-gpu{gpu}.identity.json', dict(record, gpu=gpu, port=PORTS[gpu]))
            started = time.monotonic()
            while not ready(PORTS[gpu]):
                if self.stop.is_set():
                    raise RuntimeError('queue_cancelled')
                if p.poll() is not None or time.monotonic() - started > 600:
                    raise RuntimeError('policy_start_failed')
                progress('starting_policy', gpu=gpu, process=record)
                self.stop.wait(2)

    def episode(self, gpu, row, orders, policy, path, progress, timeout=10800):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise RuntimeError('episode_output_already_exists')
        command = [AGENT_PYTHON, str(ROOT / 'stress_workflow.py'),
            '--output', str(path), '--orders', str(orders), '--port', str(PORTS[gpu]),
            '--init', str(row['init']), '--variant', str(row['variant']),
            '--jobs', str(row['jobs']), '--history', row['history'],
            '--case', row['case'], '--arm', row['effective_arm']]
        if policy is not None:
            command += ['--memory-policy', str(policy)]
        with path.with_suffix('.log').open('xb') as log:
            p = subprocess.Popen(command, cwd=ROOT, env=env(gpu),
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        record = self.track(p, 'worker')
        progress(dict(status='running', trial_id=row['trial_id'], worker=record, output=str(path)))
        started = time.monotonic()
        error = None
        try:
            while p.poll() is None:
                if self.stop.is_set():
                    error = 'queue_cancelled'
                    break
                if time.monotonic() - started > timeout:
                    error = 'worker_timeout'
                    break
                self.stop.wait(2)
            if error:
                self.stop_owned(p)
            result = path / 'result.json'
            data = json.loads(result.read_text()) if result.is_file() else {
                'status': 'infrastructure_failure',
                'error_code': error or 'worker_exit', 'return_code': p.poll()}
            # Never silently turn a cancelled or timed-out run into success.
            if error:
                data.update(status='infrastructure_failure', error_code=error)
            return dict(data, **row, output=str(path), worker_identity=record,
                        infrastructure_episode_retries=0)
        finally:
            if p.poll() is None:
                self.stop_owned(p)
            self.release_process(p)

    def close(self):
        self.stop.set()
        with self.process_lock:
            processes = list(self.processes.values())
        # Stop worker groups before serving policies, which are ours alone.
        for process, _, kind in sorted(processes, key=lambda item: item[2] == 'policy'):
            self.stop_owned(process)
            self.release_process(process)
        for handle in self.locks:
            handle.close()
        self.locks.clear()
