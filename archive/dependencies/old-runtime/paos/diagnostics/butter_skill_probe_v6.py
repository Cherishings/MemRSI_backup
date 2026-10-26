#!/usr/bin/env python3
"""Measure real scripted-gripper transport of the two easy final objects.

This is a skill assay, not a PAOS or mission-memory result.  Each seed starts
from a fresh disclosed LIBERO scene; no simulator object teleport is scored.
"""
import asyncio
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

SOURCE = Path('/data/stormlab/xi/paos/worktrees/native-long-workflow-v6-20261006')
LOCK = Path('/data/stormlab/xi/paos/qwen-deploy/paos-gpu5-run.lock')
SEEDS = tuple(range(20))
GOALS = (('front_butter', 'priority'), ('rear_butter', 'butter_cabinet'))


def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def acquire(lock):
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(5)


async def one(seed, goal, case):
    from real_breakfast_worker import World
    world = World({'output': str(case / 'simulator'), 'seed': seed,
                   'max_steps': 3000, 'policy_port': 19025,
                   'backend': 'scripted_osc_reference'})
    try:
        before = world.snapshot()
        world.last_locations = dict(before['locations'])
        world.location_transitions = []
        world.active_limit = min(world.max_steps, world.steps + 1500)
        result = world._execute_scripted(goal, before, handoff=None)
        return {'status': 'finished', 'seed': seed,
                'object_id': goal[0], 'destination': goal[1],
                'physical_success': result['success'],
                'physical_failure_reason': result.get('failure_reason'),
                'physical_steps': result.get('steps_used'),
                'final_location': result['after']['locations'][goal[0]],
                'video': str(case / 'simulator/continuous.mp4'),
                'physical_transport': True}
    finally:
        await world.close()


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: butter_skill_probe.py OUTPUT')
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(MUJOCO_GL='egl', PYOPENGL_PLATFORM='egl',
                      MUJOCO_EGL_DEVICE_ID='5', CUDA_VISIBLE_DEVICES='5')
    os.environ.setdefault('LIBERO_CONFIG_PATH', '/data/stormlab/xi/paos/config/libero')
    for path in (SOURCE, SOURCE / 'scripts',
                 Path('/home/xi/stormlab/xi/openpi'),
                 Path('/home/xi/stormlab/xi/openpi/third_party/libero')):
        sys.path.insert(0, str(path))
    save(out / 'manifest.json', {
        'protocol': 'v6-two-butter-physical-skill-assay',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_commit': 'e89116063747569bd07280ce937743294210ee62',
        'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'gpu': 5, 'goals': GOALS, 'seeds': SEEDS, 'planned': 40,
        'executor': 'scripted_osc_reference_real_gripper_no_teleport',
        'not_a_mission_or_memory_test': True})
    records = []
    for seed in SEEDS:
        for goal in GOALS:
            case = out / ('s%02d-%s' % (seed, goal[0]))
            if (case / 'result.json').exists():
                row = json.loads((case / 'result.json').read_text())
            else:
                case.mkdir(exist_ok=True)
                with LOCK.open('a') as lock:
                    acquire(lock)
                    try:
                        row = asyncio.run(one(seed, goal, case))
                    except Exception as exc:
                        row = {'status': 'probe_exception', 'seed': seed,
                               'object_id': goal[0], 'destination': goal[1],
                               'exception_type': type(exc).__name__,
                               'physical_success': False}
                save(case / 'result.json', row)
            records.append(row)
            save(out / 'progress.json', {
                'stage': 'running', 'planned': 40, 'terminal': len(records),
                'physical_success': sum(x.get('physical_success') is True for x in records),
                'records': records})
    save(out / 'progress.json', {
        'stage': 'finished', 'planned': 40, 'terminal': len(records),
        'physical_success': sum(x.get('physical_success') is True for x in records),
        'records': records})


if __name__ == '__main__':
    main()
