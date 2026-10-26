#!/usr/bin/env python3
"""One-shot black-bowl skill check in the new real-asset candidate scene.

The checker acquires GPU 0's standard lock, initializes a new candidate scene,
then attempts one pi0.5 bowl placement. This is separate from the paired
memory-comparison results and never counts as mission success.
"""

import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


ROOT = Path('/data/stormlab/xi/paos/worktrees/mission-kitchen-real-v7-3-20261003')
OUT = Path('/data/stormlab/xi/paos/validation/mission-kitchen-v7-3-front-butter-s0')
BDDL = ROOT / 'specs' / 'mission-kitchen-v7-real-scene.bddl'
GPU_LOCK = Path('/data/stormlab/xi/paos/qwen-deploy/gpt-gpu1-run.lock')
LIBERO_PYTHON = '/data/stormlab/xi/paos/venvs/libero/bin/python'
POLICY_PYTHON = '/data/stormlab/xi/paos/venvs/policy/bin/python'
PORT = 18936


def save(state):
    path = OUT / 'qualification-status.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def process_identity(pid):
    parts = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
    return {'pid': pid, 'start_ticks': parts[19]}


def same_process(identity):
    try:
        return process_identity(identity['pid']) == identity
    except OSError:
        return False


def port_open():
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(('127.0.0.1', PORT)) == 0


def run():
    OUT.mkdir(parents=True, exist_ok=False)
    state = {'stage': 'acquiring_gpu', 'identity': process_identity(os.getpid()),
             'scene': str(BDDL), 'gpu': 1, 'port': PORT}
    save(state)
    policy = None
    policy_identity = None
    try:
        with (OUT / 'singleton.lock').open('a') as singleton:
            fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with GPU_LOCK.open('a') as gpu_lock:
                fcntl.flock(gpu_lock, fcntl.LOCK_EX)
                if not BDDL.is_file():
                    raise FileNotFoundError('candidate_bddl_missing')
                env = dict(os.environ)
                env.update(CUDA_VISIBLE_DEVICES='1', MUJOCO_EGL_DEVICE_ID='1',
                           MUJOCO_GL='egl', PYOPENGL_PLATFORM='egl',
                           LIBERO_CONFIG_PATH='/data/stormlab/xi/paos/config/libero',
                           PYTHONUNBUFFERED='1')
                paths = [str(ROOT), '/home/xi/stormlab/xi/openpi',
                         '/home/xi/stormlab/xi/openpi/third_party/libero']
                if env.get('PYTHONPATH'):
                    paths.append(env['PYTHONPATH'])
                env['PYTHONPATH'] = os.pathsep.join(paths)
                state['stage'] = 'initializing'; save(state)
                with (OUT / 'initialization.log').open('wb') as log:
                    subprocess.run([LIBERO_PYTHON, '-u',
                                    str(ROOT / 'scripts/probe_candidate_scene.py'),
                                    '--bddl', str(BDDL), '--output', str(OUT / 'initial'),
                                    '--gpu', '1'], env=env, cwd=ROOT,
                                   stdout=log, stderr=log, check=True, timeout=300)
                state['initialized'] = True
                if port_open():
                    raise RuntimeError('policy_port_already_owned')
                policy_env = dict(env, PAOS_DIAG_PORT=str(PORT),
                                  XLA_PYTHON_CLIENT_MEM_FRACTION='0.85')
                state['stage'] = 'starting_policy'; save(state)
                with (OUT / 'policy.log').open('wb') as log:
                    policy = subprocess.Popen(
                        [POLICY_PYTHON, '-u', str(ROOT / 'scripts/serve_mission_policy.py')],
                        env=policy_env, cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=log, start_new_session=True)
                    policy_identity = process_identity(policy.pid)
                    state['policy'] = policy_identity; save(state)
                    deadline = time.monotonic() + 600
                    while not port_open():
                        if policy.poll() is not None:
                            raise RuntimeError('policy_exited_before_ready')
                        if time.monotonic() >= deadline:
                            raise TimeoutError('policy_startup_limit')
                        time.sleep(1)
                state['stage'] = 'probing_black_bowl'; save(state)
                with (OUT / 'probe.log').open('wb') as probe_log:
                    subprocess.run([LIBERO_PYTHON, '-u',
                                    '/data/stormlab/xi/paos/validation/probe_worker_action_v7_3.py',
                                    '--output', str(OUT / 'front_butter'),
                                    '--port', str(PORT), '--seed', '0',
                                    '--limit', '1000', '--object-id', 'front_butter',
                                    '--destination', 'priority'], env=env, cwd=ROOT,
                                   stdout=probe_log, stderr=probe_log,
                                   check=True, timeout=1800)
                report = json.loads((OUT / 'front_butter' / 'report.json').read_text())
                state['stage'] = 'finished'
                state['front_butter_skill_success'] = report['success']
                state['front_butter_steps'] = report['steps_used']
                state['failure_reason'] = report['failure_reason']
                save(state)
    except BaseException as exc:
        state['stage'] = 'failed'
        state['failure_type'] = type(exc).__name__
        save(state)
    finally:
        if policy is not None and policy_identity is not None and same_process(policy_identity):
            os.killpg(policy.pid, signal.SIGTERM)
            try:
                policy.wait(timeout=20)
            except subprocess.TimeoutExpired:
                if same_process(policy_identity):
                    os.killpg(policy.pid, signal.SIGKILL)
                policy.wait(timeout=10)
        state['policy_reaped'] = policy is None or policy.poll() is not None
        save(state)
    return 0 if state['stage'] == 'finished' else 1


if __name__ == '__main__':
    sys.exit(run())
