"""Explicit launcher; two complete study plans, no automatic budget expansion."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

import run_trial

HERE = Path(__file__).resolve().parent
ROBOT = Path('/data/stormlab/xi/robot')
CORE = Path('/data/stormlab/xi/paos/worktrees/memrsi-bounded-v2_2')
PAOS_ROOT = Path('/data/stormlab/xi/PhyAgentOS-core')
PYTHON = '/home/xi/envs/agent/bin/python'


def study_environment(benchmark):
    """Pin provider imports and the same overlays used by episode actors.

    No provider instance is constructed here. The actor overlay supplies
    setproctitle, common deps supply image/array adapters, and the agent venv
    supplies openai/httpx/json_repair/tiktoken. Explicit PAOS_ROOT prevents a
    different editable installation from silently replacing the frozen core.
    """
    overlay = ROBOT / ('official-memory-remem-r4-20261017' if benchmark == 'remem'
                       else 'official-memory-rmbench-20261017r4') / 'actor-deps'
    paths = [HERE / 'common', overlay, ROBOT / 'official-memory-common-20261017/deps', CORE, PAOS_ROOT]
    env = dict(os.environ, PYTHONPATH=':'.join(map(str, paths)), MEMRSI_FROZEN_CORE=str(CORE))
    # Proposals use their explicit, locked learning ledger. A stale actor's
    # environment must not install a second accounting path in the coordinator.
    for name in ('MEMRSI_LEARNING_LEDGER', 'MEMRSI_PHASE', 'MEMRSI_CASE_ID'):
        env.pop(name, None)
    return env


def run(args):
    if args.rmbench_gpu == args.remem_gpu:
        raise ValueError('distinct_gpus_required')
    if any(type(gpu) is not int or gpu not in range(8) for gpu in (args.rmbench_gpu, args.remem_gpu)):
        raise ValueError('gpu_outside_authorized_range')
    qualification = json.loads(args.qualification.read_text())
    hashes = run_trial.source_hashes()
    if qualification.get('passed') is not True or qualification.get('source_hashes') != hashes:
        raise ValueError('engineering_qualification_missing_or_source_changed')
    remaining = run_trial.learning_budget_remaining(args.ledger)
    if remaining < 480:
        raise ValueError('insufficient_authorized_episode_capacity_no_gpu_started')
    args.output.mkdir(parents=True, exist_ok=True)
    launched, skipped = [], []
    with (args.output / 'launch.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if run_trial.source_hashes() != hashes:
            raise ValueError('source_changed_before_launch')
        for benchmark, gpu in [('rmbench', args.rmbench_gpu), ('remem', args.remem_gpu)]:
            folder = args.output / benchmark
            folder.mkdir(exist_ok=True)
            pointer = folder / 'coordinator.json'
            if (folder / 'study-complete.json').exists():
                skipped.append({'benchmark': benchmark, 'reason': 'already_complete'})
                continue
            if pointer.exists() and run_trial.matches_identity(json.loads(pointer.read_text())):
                skipped.append({'benchmark': benchmark, 'reason': 'coordinator_alive'})
                continue
            # A previous launcher can die before publishing its pointer. The
            # study's own lock remains an independent duplicate-start barrier.
            with (folder / 'study.lock').open('a') as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    skipped.append({'benchmark': benchmark, 'reason': 'study_lock_held'})
                    continue
                # Release before spawn: run_study opens and acquires this lock
                # itself. launch.lock serializes all calls to this launcher.
                fcntl.flock(probe, fcntl.LOCK_UN)
            env = study_environment(benchmark)
            command = [PYTHON, str(HERE / 'run_study.py'), '--benchmark', benchmark,
                       '--gpu', str(gpu), '--policy', str(HERE / 'policies/initial.json'),
                       '--ledger', str(args.ledger.resolve()), '--qualification', str(args.qualification.resolve()),
                       '--output', str(folder)]
            with (folder / 'coordinator.private.log').open('a') as output:
                child = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                         stdout=output, stderr=output, start_new_session=True)
            info = dict(run_trial.identity(child.pid), benchmark=benchmark, gpu=gpu,
                        output=str(folder), time=time.time())
            if pointer.exists():
                with (folder / 'coordinator-history.jsonl').open('a') as history:
                    history.write(json.dumps(json.loads(pointer.read_text())) + '\n')
            run_trial.write(pointer, info)
            launched.append(info)
    return {'started': launched, 'skipped': skipped, 'learning_remaining': remaining,
            'learning_cap_unchanged': True, 'formal_pairs_per_benchmark': 48,
            'rules_frozen_during_formal_test': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rmbench-gpu', type=int, choices=range(8), required=True)
    parser.add_argument('--remem-gpu', type=int, choices=range(8), required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROBOT / 'runs/official-memory-v5-studies-20261017')
    print(json.dumps(run(parser.parse_args())))


if __name__ == '__main__':
    main()
