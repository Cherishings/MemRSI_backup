#!/usr/bin/env python3
"""Finite, one-shot seed pair: execution reference, native PAOS, TaskMemory PAOS."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


TERMINAL = {'finished', 'failed', 'error', 'stopped', 'blocked', 'cleanup_incomplete'}


def save(path, row):
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def terminal_status(root, deadline):
    while time.monotonic() < deadline:
        path = root / 'launcher-status.json'
        if path.exists():
            try:
                row = json.loads(path.read_text())
            except json.JSONDecodeError:
                time.sleep(10)
                continue
            if row.get('stage') in TERMINAL:
                return row
        time.sleep(10)
    return {'stage': 'wait_expired'}


def launch(root, controller, gpu, seed, launcher, counts):
    if root.exists():
        return {'stage': 'output_already_exists', 'controller': controller}
    command = [sys.executable, str(launcher), 'launch', '--gpu', str(gpu),
               '--seed', str(seed), '--controller', controller,
               '--executor', 'scripted_osc_reference', '--output', str(root),
               '--mission-counts', json.dumps(counts, separators=(',', ':'))]
    completed = subprocess.run(command, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, timeout=60)
    return {'stage': 'launched' if completed.returncode == 0 else 'launch_failed',
            'controller': controller, 'returncode': completed.returncode}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('reference', 'native', 'task-memory', 'status'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--gpu', type=int, choices=(0, 1), required=True)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args()
    status = args.status
    save(status, {'stage': 'waiting_for_execution_reference', 'automatic_retries': 0})
    reference_status = terminal_status(args.reference, time.monotonic() + 9000)
    try:
        reference_result = json.loads((args.reference / 'episode/result.json').read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        reference_result = {}
    report = reference_result.get('contract') or {}
    executable = (reference_status.get('stage') == 'finished'
                  and reference_result.get('status') == 'completed'
                  and report.get('physical_terminals_pass') is True
                  and report.get('workflow_events_reached') is True
                  and report.get('physical_mission_violation_count') == 0)
    if not executable:
        save(status, {'stage': 'reference_not_executable', 'automatic_retries': 0,
                      'reference_status': reference_result.get('status'),
                      'failure_domain': reference_result.get('failure_domain'),
                      'reason': reference_result.get('reason')})
        return 1
    # Launch both methods from the reference's frozen source copy.  The live
    # worktree may change while this finite dependent schedule is waiting.
    launcher = args.reference / 'code/scripts/launch_mission_v4.py'
    counts = json.loads((args.reference / 'task.json').read_text())['counts']
    native_launch = launch(args.native, 'paos', args.gpu, args.seed, launcher, counts)
    save(status, {'stage': 'native_' + native_launch['stage'],
                  'automatic_retries': 0, 'native': native_launch})
    if native_launch['stage'] != 'launched':
        return 2
    native_status = terminal_status(args.native, time.monotonic() + 9000)
    if native_status.get('stage') not in ('finished', 'failed') or not (args.native / 'episode/result.json').exists():
        save(status, {'stage': 'native_unusable', 'automatic_retries': 0,
                      'native_stage': native_status.get('stage')})
        return 3
    memory_launch = launch(args.task_memory, 'paos_task_memory', args.gpu, args.seed, launcher, counts)
    save(status, {'stage': 'memory_' + memory_launch['stage'],
                  'automatic_retries': 0, 'native_stage': native_status.get('stage'),
                  'memory': memory_launch})
    return 0 if memory_launch['stage'] == 'launched' else 4


if __name__ == '__main__':
    raise SystemExit(main())
