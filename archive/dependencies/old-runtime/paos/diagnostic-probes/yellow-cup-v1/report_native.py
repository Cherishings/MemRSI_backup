#!/usr/bin/env python3
"""Read-only, compact status for the native PAOS long-mission experiments."""
import json
from collections import Counter
from pathlib import Path

BASE = Path('/data/stormlab/xi/paos/results')
PHYSICAL = BASE / 'native-memory-diagnostic-v2-20261005T161809Z'
ATOMIC_POINTER = Path('/data/stormlab/xi/paos/qwen-deploy/latest-native-atomic-diagnostic-v3.txt')
SKILL = BASE / 'yellow-cup-skill-v1-20261005T171013Z'
LONG_POINTER = Path('/data/stormlab/xi/paos/qwen-deploy/latest-native-long-workflow-v4.txt')


def live(identity_file):
    if not identity_file.exists():
        return None
    owner = json.loads(identity_file.read_text())
    try:
        stat = (Path('/proc') / str(owner['pid']) / 'stat').read_text()
        ticks = int(stat.rsplit(') ', 1)[1].split()[19])
        return ticks == int(owner['start_ticks'])
    except (OSError, KeyError, ValueError, IndexError):
        return False


def status(path, kind):
    progress = json.loads((path / 'progress.json').read_text())
    records = progress.get('records', [])
    return {
        'kind': kind,
        'root': str(path),
        'stage': progress.get('stage'),
        'terminal_cases': progress.get('terminal_cases', progress.get('completed')),
        'planned_cases': progress.get('planned_cases', progress.get('planned')),
        'checkpoint_planned': progress.get('planned_checkpoints'),
        'checkpoint_reached': progress.get('reached_checkpoints'),
        'checkpoint_correct': progress.get('correct_checkpoints'),
        'mission_success': sum(bool(row.get('mission_success') or
                                    row.get('diagnostic_mission_success'))
                               for row in records),
        'failure_domains': dict(Counter(row.get('failure_domain') for row in records
                                        if row.get('failure_domain'))),
        'queue_alive': live(path / 'queue-identity.json'),
        'probe_alive': live(path / 'probe-identity.json'),
    }


def long_status(path):
    progress = json.loads((path / 'progress.json').read_text())
    dependency = path / 'dependency.json'
    return {
        'kind': 'native_paos_continuous_service_atomic_diagnostic',
        'root': str(path), 'stage': progress.get('stage'),
        'oracle_cases': progress.get('terminal_oracle_cases'),
        'native_cases': progress.get('terminal_native_cases'),
        'planned_oracle_cases': progress.get('planned_oracle_cases'),
        'planned_native_cases': progress.get('planned_native_cases'),
        'oracle_reachable': progress.get('oracle_reachable'),
        'native_mission_success': progress.get('native_mission_success'),
        'checkpoint_planned': progress.get('planned_native_checkpoints'),
        'checkpoint_reached': progress.get('reached_native_checkpoints'),
        'checkpoint_correct': progress.get('correct_native_checkpoints'),
        'dependencies': (json.loads(dependency.read_text()).get('states')
                         if dependency.exists() else None),
        'queue_alive': live(path / 'queue-identity.json'),
    }


def main():
    atomic = Path(ATOMIC_POINTER.read_text().strip())
    result = {
        'native_physical': status(PHYSICAL, 'real_osc_transport'),
        'native_atomic': status(atomic, 'privileged_simulator_object_placement'),
        'yellow_cup_skill': status(SKILL, 'real_osc_single_skill'),
        'interpretation': 'Correct/reached is conditional on reaching a checkpoint; physical and atomic mission successes are not interchangeable.'
    }
    if LONG_POINTER.exists():
        result['native_long_workflow'] = long_status(Path(LONG_POINTER.read_text().strip()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
