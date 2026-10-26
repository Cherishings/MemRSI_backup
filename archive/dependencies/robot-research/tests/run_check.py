#!/usr/bin/env python3
"""Safe entry point for simulator checks; no agent or task-success claim."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path('/data/stormlab/xi/robot')
LEASES = Path('/data/stormlab/xi/paos/qwen-deploy')


def lock_name(gpu):
    return 'robot-run.lock' if gpu == 0 else f'gpt-gpu{gpu}-run.lock'


def acquire(path, wait, used_memory, sleep=time.sleep):
    """Respect both PAOS leases and non-cooperating GPU users."""
    lease = path.open('a')
    announced = False
    try:
        while True:
            locked = False
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError:
                pass
            if locked:
                try:
                    available = used_memory() <= 1024
                except BaseException:
                    fcntl.flock(lease, fcntl.LOCK_UN)
                    raise
                if available:
                    return lease
                fcntl.flock(lease, fcntl.LOCK_UN)
            if not wait:
                raise RuntimeError('gpu_busy_no_test_started')
            if not announced:
                print('GPU busy; waiting. Existing experiments are unchanged.', flush=True)
                announced = True
            sleep(10)
    except BaseException:
        lease.close()
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('platform', choices=['twin', 'casa'])
    p.add_argument('--gpu', type=int, choices=[0, 1, 2], required=True)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--steps', type=int, default=8)
    p.add_argument('--wait', action='store_true', help='wait for the selected GPU')
    a = p.parse_args()
    if not 1 <= a.steps <= 1000:
        p.error('steps must be 1..1000')
    os.umask(0o077)
    ready = json.loads((ROOT/'setup'/f'ready-{a.platform}.json').read_text())
    if ready.get('phase') != 'ready':
        p.error('platform setup is not ready')
    def used():
        return int(subprocess.check_output([
            'nvidia-smi', '-i', str(a.gpu), '--query-gpu=memory.used',
            '--format=csv,noheader,nounits'], text=True).strip())
    try:
        lease = acquire(LEASES/lock_name(a.gpu), a.wait, used)
    except RuntimeError as e:
        print(json.dumps({'status': str(e), 'gpu': a.gpu}), flush=True)
        return 3
    with lease:
        folder = ROOT/'runs'/('check-'+a.platform+'-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True, exist_ok=False)
        output = folder/'episode'
        command = [str(ROOT/'bin/robot'), a.platform, str(a.gpu),
                   str(ROOT/'tests'/f'check_{a.platform}.py'),
                   '--seed', str(a.seed), '--steps', str(a.steps), '--output', str(output)]
        meta = dict(platform=a.platform, gpu=a.gpu, seed=a.seed, steps=a.steps,
                    scope='environment setup check only', output=str(output), started_unix=time.time())
        (folder/'launch.json').write_text(json.dumps(meta, indent=2))
        print('Output: '+str(folder), flush=True)
        with (folder/'run.log').open('x') as log:
            child = subprocess.Popen(command, stdout=log, stderr=log,
                                     stdin=subprocess.DEVNULL, pass_fds=(lease.fileno(),))
            code = child.wait()
        path = output/'result.json'
        result = json.loads(path.read_text()) if path.exists() else {'status': 'failed'}
        passed = code == 0 and result.get('status') == 'passed'
        summary = dict(meta, exit_code=code, status='passed' if passed else 'failed',
                       result=result, finished_unix=time.time())
        (folder/'summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
        return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
