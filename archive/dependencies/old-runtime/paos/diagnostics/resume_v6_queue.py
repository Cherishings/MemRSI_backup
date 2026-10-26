#!/usr/bin/env python3
"""Finite native-PAOS hidden-history queue; terminal cases are never retried."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from threading import Lock
import time

ROOT = Path('/data/stormlab/xi/paos/worktrees/native-long-workflow-v6-20261006')
DEPLOY = Path('/data/stormlab/xi/paos/qwen-deploy')
PYTHON = '/home/xi/envs/agent/bin/python'
GPUS = (3, 4, 5, 0, 1)
SEEDS = tuple(range(20))
CONDITIONS = ('front_butter_final', 'rear_butter_final')
STAGES = (
    ('oracle', 'oracle_reference', 'full', 'hidden'),
    ('hidden_probe', 'paos', 'fixed_prefix_probe', 'hidden'),
    ('full', 'paos', 'full', 'hidden'),
    ('visible_probe', 'paos', 'fixed_prefix_probe', 'visible'),
    ('rescue_probe', 'paos', 'fixed_prefix_probe', 'rescue'),
)
SOURCES = ('long_mission_contract.py', 'real_breakfast_worker.py',
           'run_breakfast.py', 'launch_breakfast.py', 'run_long_native_queue.py')


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def alive(identity_file):
    try:
        row = json.loads(identity_file.read_text())
        fields = (Path('/proc') / str(row['pid']) / 'stat').read_text().rsplit(') ', 1)[1].split()
        return fields[0] != 'Z' and int(fields[19]) == int(row['start_ticks'])
    except (OSError, ValueError, KeyError, IndexError):
        return False


def case_id(stage, seed, condition):
    return 's%02d-%s-%s' % (seed, condition, stage)


def summarize(case, stage, seed, condition, gpu):
    file = case / 'episode/result.json'
    result = json.loads(file.read_text()) if file.exists() else {}
    contract = result.get('contract') or {}
    return {
        'case_id': case.name, 'case': str(case), 'stage': stage,
        'seed': seed, 'condition': condition, 'gpu': gpu,
        'status': result.get('status', 'missing_result'),
        'exit_code': int((case / 'exit-code.txt').read_text()),
        'failure_domain': result.get('failure_domain'), 'reason': result.get('reason'),
        'mission_success': result.get('mission_success') if stage == 'full' else None,
        'oracle_goal_reached': (stage == 'oracle' and result.get('status') == 'completed'
                                and contract.get('terminal_facts_valid') is True),
        'probe_reached': result.get('probe_reached') if 'probe' in stage else None,
        'probe_answer_correct': result.get('probe_answer_correct') if 'probe' in stage else None,
        'final_scene_hash': result.get('final_scene_hash') if 'probe' in stage else None,
        'final_cue': result.get('final_cue') if 'probe' in stage else None,
        'checkpoint_reached': contract.get('checkpoint_reached'),
        'checkpoint_correct': contract.get('checkpoint_correct'),
        'session_switches': contract.get('session_switches'),
        'agent_decisions': result.get('agent_decisions'),
        'fixed_prefix_moves': result.get('fixed_prefix_moves'),
        'execution_failures': len(result.get('execution_failures') or []),
        'result': str(file) if result else None,
    }


def launch_or_attach(out, stage, controller, mode, cue, seed, condition, gpu):
    case = out / case_id(stage, seed, condition)
    if not case.exists():
        cmd = [PYTHON, str(ROOT / 'scripts/launch_breakfast.py'), 'launch',
               '--output', str(case), '--gpu', str(gpu), '--seed', str(seed),
               '--condition', condition, '--controller', controller,
               '--mode', mode, '--cue', cue, '--executor', 'diagnostic_atomic',
               '--policy-port', str(19020 + gpu), '--action-steps', '1000',
               '--max-steps', '36000', '--max-actions', '160',
               '--max-calls', '500', '--wall-seconds', '5400']
        launched = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                  text=True, check=True, timeout=120)
        if Path(json.loads(launched.stdout)['output']) != case:
            raise RuntimeError('launcher_output_mismatch')
    owner = case / 'launcher-identity.json'
    if not owner.exists():
        return {'case_id': case.name, 'stage': stage, 'seed': seed,
                'condition': condition, 'gpu': gpu, 'status': 'launch_incomplete'}
    while not (case / 'exit-code.txt').exists():
        if not alive(owner):
            return {'case_id': case.name, 'stage': stage, 'seed': seed,
                    'condition': condition, 'gpu': gpu, 'status': 'launcher_lost'}
        time.sleep(5)
    return summarize(case, stage, seed, condition, gpu)


def progress(out, records, stage, active=()):
    by_stage = {name: [r for r in records if r.get('stage') == name]
                for name, *_ in STAGES}
    hidden = {(r.get('seed'), r.get('condition')): r
              for r in by_stage['hidden_probe']}
    paired = [(hidden.get((seed, CONDITIONS[0]), {}),
               hidden.get((seed, CONDITIONS[1]), {})) for seed in SEEDS]
    pair_scene_matched = sum(bool(a.get('final_scene_hash')) and
                             a.get('final_scene_hash') == b.get('final_scene_hash') and
                             a.get('final_cue') == b.get('final_cue') == '继续。'
                             for a, b in paired)
    pair_both_correct = sum(
        bool(a.get('final_scene_hash')) and a.get('final_scene_hash') == b.get('final_scene_hash')
        and a.get('final_cue') == b.get('final_cue') == '继续。'
        and a.get('probe_answer_correct') is True
        and b.get('probe_answer_correct') is True
        for a, b in paired)
    save(out / 'progress.json', {
        'stage': stage, 'planned_total': 200, 'terminal_total': len(records),
        'terminal_by_stage': {key: len(value) for key, value in by_stage.items()},
        'native_full_success': sum(r.get('mission_success') is True for r in by_stage['full']),
        'oracle_goal_reached': sum(r.get('oracle_goal_reached') is True for r in by_stage['oracle']),
        'hidden_probe_reached': sum(r.get('probe_reached') is True for r in by_stage['hidden_probe']),
        'hidden_probe_correct': sum(r.get('probe_answer_correct') is True for r in by_stage['hidden_probe']),
        'hidden_pair_both_correct': pair_both_correct,
        'hidden_pair_scene_matched': pair_scene_matched,
        'active_cases': list(active), 'records': records,
        'manifest': str(out / 'manifest.json')})


def run_stage(out, name, controller, mode, cue, records, seeds=SEEDS):
    known = {r.get('case_id') for r in records}
    tasks = [(seed, condition) for seed in seeds for condition in CONDITIONS
             if case_id(name, seed, condition) not in known]
    by_gpu = {gpu: [] for gpu in GPUS}
    for index, (seed, condition) in enumerate(tasks):
        case = out / case_id(name, seed, condition)
        config_file = case / 'launch.json'
        gpu = (json.loads(config_file.read_text())['gpu']
               if config_file.exists() else GPUS[index % len(GPUS)])
        by_gpu[gpu].append((seed, condition))
    active = set()
    mutex = Lock()

    def worker(gpu):
        for seed, condition in by_gpu[gpu]:
            key = case_id(name, seed, condition)
            with mutex:
                active.add(key)
                progress(out, records, 'running_' + name, active)
            try:
                row = launch_or_attach(out, name, controller, mode,
                                       cue, seed, condition, gpu)
            except Exception as exc:
                row = {'case_id': key, 'stage': name, 'seed': seed,
                       'condition': condition, 'gpu': gpu,
                       'status': 'batch_exception', 'exception_type': type(exc).__name__}
            with mutex:
                records.append(row)
                active.remove(key)
                progress(out, records, 'running_' + name, active)

    with ThreadPoolExecutor(max_workers=len(GPUS)) as pool:
        futures = [pool.submit(worker, gpu) for gpu in GPUS]
        for future in futures:
            future.result()


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: run_long_native_queue.py OUTPUT')
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                         cwd=ROOT, text=True).strip()
        hashes = {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                  for name in SOURCES}
        manifest = {'protocol': 'native-paos-hidden-history-v6',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'source_commit': commit, 'source_hashes': hashes,
                    'seeds': SEEDS, 'conditions': CONDITIONS,
                    'stages': [name for name, *_ in STAGES],
                    'planned_cases_per_stage': 40, 'planned_total': 200,
                    'authorized_gpus': GPUS,
                    'main_executor': 'privileged_simulator_atomic_object_placement',
                    'physical_transport_claim': False,
                    'fixed_prefix_probe_disclosure': 'Oracle performs the prefix; native PAOS only answers the final hidden-history decision.',
                    'case_retry_policy': 'no automatic retry of terminal model or capability failure',
                    'history_pair_rule': 'same seed and final scene, same continue cue, different day-one commitment; both answers must be correct'}
        file = out / 'manifest.json'
        if file.exists():
            old = json.loads(file.read_text())
            if old['source_commit'] != commit or old['source_hashes'] != hashes:
                raise RuntimeError('frozen_source_mismatch')
        else:
            save(file, manifest)
        save(out / 'scheduler-recovery-v2.json', {
            'reason': 'per-GPU independent workers avoid blocked GPUs preventing work on free GPUs',
            'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'original_manifest_preserved': True,
            'completed_cases_reused_without_rerun': True,
            'existing_live_coordinators_attached_by_case_id': True,
            'started_at': datetime.now(timezone.utc).isoformat()})
        (DEPLOY / 'latest-native-long-workflow-v6.txt').write_text(str(out) + '\n')
        old_progress = out / 'progress.json'
        records = json.loads(old_progress.read_text()).get('records', []) if old_progress.exists() else []
        progress(out, records, 'starting')
        run_stage(out, *STAGES[0], records, seeds=(0,))
        first = [r for r in records if r.get('stage') == 'oracle' and r.get('seed') == 0]
        if len(first) != 2 or not all(r.get('oracle_goal_reached') is True for r in first):
            progress(out, records, 'qualification_failed')
            save(out / 'qualification-failure.json', {
                'reason': 'seed0_paired_oracle_did_not_reach_goal', 'records': first})
            return
        for stage in STAGES:
            run_stage(out, *stage, records)
        progress(out, records, 'finished')
        save(out / 'final-report.json', {
            'source_commit': commit,
            'by_stage': {name: {'terminal': sum(r.get('stage') == name for r in records),
                               'failure_domains': dict(Counter(r.get('failure_domain') for r in records
                                                               if r.get('stage') == name and r.get('failure_domain')))}
                         for name, *_ in STAGES},
            'pair_both_correct': json.loads((out / 'progress.json').read_text())['hidden_pair_both_correct'],
            'interpretation': 'Autonomous full runs, fixed-prefix history probes, visible cue, and verified-history rescue are separate evidence. Atomic placement is not physical grasping.'})


if __name__ == '__main__':
    main()
