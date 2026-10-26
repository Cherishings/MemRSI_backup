#!/usr/bin/env python3
"""Read-only status/report for the physical, atomic, and skill-only arms."""
from collections import Counter
import json
from pathlib import Path
import sys

V2 = Path('/data/stormlab/xi/paos/results/native-memory-diagnostic-v2-20261005T161809Z')
CHECKPOINTS = ('priority_decision', 'session_resume',
               'post_revision_decision', 'replacement_decision')


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def include_finished_case_files(root, records):
    """A queue may wait for its paired GPU before recording a finished case."""
    combined = list(records)
    known = {(r.get('seed'), r.get('condition'), r.get('controller'))
             for r in combined}
    for case in root.iterdir():
        if not case.is_dir() or not case.name.startswith('s'):
            continue
        result = read(case / 'episode/result.json')
        spec = read(case / 'task.json')
        if not result or not spec:
            continue
        key = (result.get('seed'), spec.get('condition'), result.get('controller'))
        if key in known:
            continue
        contract = result.get('contract') or {}
        combined.append({'seed': key[0], 'condition': key[1], 'controller': key[2],
                         'status': result.get('status'),
                         'failure_domain': result.get('failure_domain'),
                         'reason': result.get('reason'),
                         'checkpoints': contract.get('checkpoints') or {},
                         'mission_success': result.get('mission_success'),
                         'diagnostic_mission_success': result.get('diagnostic_mission_success')})
        known.add(key)
    return combined


def arm(rows, planned):
    checks = {}
    for name in CHECKPOINTS:
        observed = [r['checkpoints'][name] for r in rows
                    if isinstance(r.get('checkpoints', {}).get(name), dict)
                    and r['checkpoints'][name].get('reached') is True]
        checks[name] = {'planned': planned, 'reached': len(observed),
                        'correct': sum(x.get('correct') is True for x in observed),
                        'correct_given_reached':
                            sum(x.get('correct') is True for x in observed) / len(observed)
                            if observed else None}
    return {'planned_cases': planned, 'terminal_cases': len(rows),
            'terminal_status': dict(Counter(r.get('status') for r in rows)),
            'failure_domains': dict(Counter(r.get('failure_domain') for r in rows
                                    if r.get('failure_domain'))),
            'full_mission_success': sum(r.get('mission_success') is True or
                                        r.get('diagnostic_mission_success') is True for r in rows),
            'checkpoints': checks}


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: report_dual.py ATOMIC_ROOT SKILL_ROOT')
    atomic = Path(sys.argv[1]); skill = Path(sys.argv[2])
    physical_state = read(V2 / 'progress.json')
    atomic_state = read(atomic / 'progress.json')
    skill_state = read(skill / 'progress.json')
    physical_rows = include_finished_case_files(V2, physical_state.get('records', []))
    atomic_rows = include_finished_case_files(atomic, atomic_state.get('records', []))
    physical = arm(physical_rows, 40)
    atomic_results = {name: arm([r for r in atomic_rows if r.get('controller') == name], 40)
                      for name in ('paos', 'paos_task_memory')}
    skill_rows = skill_state.get('records', [])
    skill_results = {stage: {'planned': 20,
                             'completed': sum(r.get('stage') == stage for r in skill_rows),
                             'physical_success': sum(r.get('stage') == stage and
                                                     r.get('physical_success') is True
                                                     for r in skill_rows),
                             'failures': dict(Counter(r.get('physical_failure_reason')
                                                      or r.get('status') for r in skill_rows
                                                      if r.get('stage') == stage and
                                                      r.get('physical_success') is not True))}
                     for stage in ('source_to_plate', 'plate_to_staging')}
    output = {'physical_v2': {'stage': physical_state.get('stage'),
                              'evidence': 'real scripted OSC transport in one LIBERO scene',
                              **physical},
              'atomic_v3': {'stage': atomic_state.get('stage'),
                            'evidence': 'privileged simulator object placement, no physical transport',
                            'qualifications': [{k:r.get(k) for k in ('condition','status','exit_code',
                                                                      'atomic_transitions','atomic_failures')}
                                               for r in atomic_rows
                                               if r.get('controller') == 'oracle_reference'],
                            'arms': atomic_results},
              'physical_skill_probe': {'stage': skill_state.get('stage'),
                                       'evidence': 'physical OSC move; atomic setup only for plate-to-staging',
                                       'stages': skill_results}}
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
