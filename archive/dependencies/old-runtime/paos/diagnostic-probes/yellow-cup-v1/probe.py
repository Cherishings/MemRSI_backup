#!/usr/bin/env python3
"""Isolated physical skill assay, separate from the frozen memory batch.

For 20 seeds, measure scripted OSC yellow-cup transport from the table to the
right plate and from the right plate to the staging area. The second assay
uses one explicitly disclosed simulator-atomic setup move to reach the plate;
its scored move is still real OSC/gripper control. It neither runs PAOS nor
claims full-mission success. It waits for the v2 physical batch to finish and
acquires the existing standard GPU-0 lock for each case.
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

SOURCE = Path('/data/stormlab/xi/paos/worktrees/native-memory-diagnostic-v3-20261006')
V2 = Path('/data/stormlab/xi/paos/results/native-memory-diagnostic-v2-20261005T161809Z')
LOCK = Path('/data/stormlab/xi/paos/qwen-deploy/robot-run.lock')
STAGES = ('source_to_plate', 'plate_to_staging')
SEEDS = tuple(range(20))


def save(path, value):
    p = Path(path)
    temp = p.with_suffix(p.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(p)


def wait_for_v2(out):
    deadline = time.monotonic() + 48 * 3600
    while time.monotonic() < deadline:
        progress = V2 / 'progress.json'
        if progress.exists():
            state = json.loads(progress.read_text())
            if state.get('stage') == 'finished':
                return
        save(out / 'progress.json', {'stage': 'waiting_for_frozen_physical_batch',
                                    'completed': 0, 'planned': len(SEEDS) * len(STAGES)})
        time.sleep(60)
    raise TimeoutError('physical_batch_dependency_not_terminal_after_48_hours')


def acquire(lock_file):
    while True:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(5)


async def one(seed, stage, case):
    # Import the immutable committed v3 worker. This script is outside that
    # worktree so no case silently receives a modified mission/controller.
    sys.path.insert(0, str(SOURCE / 'scripts'))
    sys.path.insert(0, str(SOURCE))
    from real_breakfast_worker import World
    world = World({'output': str(case / 'simulator'), 'seed': seed,
                   'max_steps': 3000, 'policy_port': 18971,
                   'backend': 'diagnostic_atomic'})
    try:
        setup = None
        if stage == 'plate_to_staging':
            state = world.snapshot()
            world.last_locations = dict(state['locations'])
            world.location_transitions = []
            world.active_limit = min(world.max_steps, world.steps + 100)
            setup = world._execute_atomic(('yellow_cup', 'order_b'), state)
            if not setup['success']:
                return {'status': 'setup_failed', 'seed': seed, 'stage': stage,
                        'setup_failure': setup.get('failure_reason'),
                        'scored_physical_move_executed': False}
        state = world.snapshot()
        world.last_locations = dict(state['locations'])
        world.location_transitions = []
        world.active_limit = min(world.max_steps, world.steps + 1000)
        goal = ('yellow_cup', 'order_b' if stage == 'source_to_plate' else 'revised_cup')
        measured = world._execute_scripted(goal, state, handoff=None)
        return {'status': 'finished', 'seed': seed, 'stage': stage,
                'setup': 'none' if setup is None else 'privileged_atomic_to_plate',
                'scored_physical_move_executed': True,
                'physical_success': measured['success'],
                'physical_failure_reason': measured.get('failure_reason'),
                'physical_steps': measured.get('steps_used'),
                'initial_location': state['locations']['yellow_cup'],
                'final_location': measured['after']['locations']['yellow_cup'],
                'physical_transport': True,
                'video': str(case / 'simulator/continuous.mp4')}
    finally:
        await world.close()


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: yellow_cup_skill_probe.py OUTPUT')
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ['MUJOCO_GL'] = 'egl'
    os.environ['PYOPENGL_PLATFORM'] = 'egl'
    os.environ['MUJOCO_EGL_DEVICE_ID'] = '0'
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    os.environ.setdefault('LIBERO_CONFIG_PATH', '/data/stormlab/xi/paos/config/libero')
    for path in ('/home/xi/stormlab/xi/openpi',
                 '/home/xi/stormlab/xi/openpi/third_party/libero'):
        sys.path.insert(0, path)
    save(out / 'manifest.json', {
        'protocol': 'yellow-cup-isolated-physical-skill-v1',
        'source_commit': '6059f28b414534fcfd3fbac2cefa4a918157c125',
        'source_path': str(SOURCE),
        'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'seeds': SEEDS, 'stages': STAGES, 'planned': len(SEEDS) * len(STAGES),
        'executor': 'scripted_osc_reference',
        'plate_to_staging_setup': 'privileged simulator atomic placement; not counted as physical skill success',
        'analysis': 'Report source-to-plate and plate-to-staging physical success separately, with failures and reasons. Do not infer mission-memory capability from this skill-only assay.',
        'gpu_lock': str(LOCK),
        'created_at': datetime.now(timezone.utc).isoformat()})
    wait_for_v2(out)
    records = []
    for seed in SEEDS:
        for stage in STAGES:
            case = out / ('s%02d-%s' % (seed, stage))
            case.mkdir(exist_ok=False)
            with LOCK.open('a') as lock_file:
                acquire(lock_file)
                try:
                    row = asyncio.run(one(seed, stage, case))
                except Exception as exc:
                    row = {'seed': seed, 'stage': stage, 'status': 'probe_exception',
                           'exception_type': type(exc).__name__,
                           'scored_physical_move_executed': False}
            save(case / 'result.json', row)
            records.append(row)
            save(out / 'progress.json', {'stage': 'running',
                 'planned': len(SEEDS) * len(STAGES), 'completed': len(records),
                 'physical_success': sum(r.get('physical_success') is True for r in records),
                 'records': records})
    save(out / 'progress.json', {'stage': 'finished',
         'planned': len(SEEDS) * len(STAGES), 'completed': len(records),
         'physical_success': sum(r.get('physical_success') is True for r in records),
         'records': records})


if __name__ == '__main__':
    main()
