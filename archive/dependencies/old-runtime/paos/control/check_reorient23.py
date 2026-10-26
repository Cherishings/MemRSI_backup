#!/usr/bin/env python3
"""Read-only status of the finite matched PAOS / TaskMemory experiment."""
import json
from pathlib import Path


BASE = Path('/data/stormlab/xi/paos/results')
CASES = {
    0: ('mission-v4-compact15', '20261003T0715Z'),
    1: ('mission-v4-compact15', '20261003T0710Z'),
}


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def identity_alive(row):
    pid, ticks = row.get('pid'), row.get('start_ticks')
    if not isinstance(pid, int) or not isinstance(ticks, int):
        return False
    try:
        return int(Path('/proc/{}/stat'.format(pid)).read_text().split()[21]) == ticks
    except (OSError, ValueError, IndexError):
        return False


def brief(root):
    launcher = read(root / 'launcher-status.json')
    result = read(root / 'episode/result.json')
    progress = result or read(root / 'episode/progress.json')
    contract = progress.get('contract') or {}
    return {
        'launcher': launcher.get('stage', '未启动'),
        'status': progress.get('status', '-'),
        'actions': progress.get('actions', '-'),
        'physical_steps': progress.get('physics_steps', '-'),
        'workflow_events_reached': contract.get('workflow_events_reached', '-'),
        'physical_terminals_pass': contract.get('physical_terminals_pass', '-'),
        'mission_success': progress.get('mission_success', '-'),
        'failure_domain': progress.get('failure_domain', '-'),
        'reason': progress.get('reason', '-'),
    }


for seed, (tag, stamp) in CASES.items():
    pair = BASE / '{}-pair-s{}-{}'.format(tag, seed, stamp)
    scheduler = read(pair / 'status.json')
    print('seed={} 配对队列={} 协调器存活={}'.format(
        seed, scheduler.get('stage', '-'), identity_alive(read(pair / 'identity.json'))))
    for role in ('reference', 'native', 'memory'):
        root = BASE / '{}-{}-s{}-{}'.format(tag, role, seed, stamp)
        print('  {:9s} {}'.format(role, json.dumps(brief(root), ensure_ascii=False)))
