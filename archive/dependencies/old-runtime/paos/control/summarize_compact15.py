#!/usr/bin/env python3
"""Read-only evidence summary for the two matched full-mission seeds."""
import json
from pathlib import Path

from compare_pair import compare


BASE = Path('/data/stormlab/xi/paos/results')
STAMPS = {0: '20261003T0715Z', 1: '20261003T0710Z'}


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def concise(root):
    result = read(root / 'episode/result.json')
    progress = result or read(root / 'episode/progress.json')
    contract = progress.get('contract') or {}
    return {
        'terminal': bool(result),
        'status': progress.get('status'),
        'role': progress.get('role'),
        'actions': progress.get('actions'),
        'successful_moves': progress.get('successful_moves'),
        'failed_moves': progress.get('failed_moves'),
        'simulation_seconds': progress.get('simulation_seconds') or contract.get('simulation_seconds'),
        'mission_success': progress.get('mission_success'),
        'failure_domain': progress.get('failure_domain'),
        'reason': progress.get('reason'),
        'physical_terminals_pass': contract.get('physical_terminals_pass'),
        'workflow_events_reached': contract.get('workflow_events_reached'),
        'checkpoint_planned': contract.get('checkpoint_planned'),
        'checkpoint_reached': contract.get('checkpoint_reached'),
        'checkpoint_correct': contract.get('checkpoint_correct'),
        'checkpoint_coverage': contract.get('checkpoint_coverage'),
        'checkpoint_accuracy_given_reached': contract.get('checkpoint_accuracy'),
        'physical_mission_violation_count': contract.get('physical_mission_violation_count'),
        'physical_state_uncertainty_count': contract.get('physical_state_uncertainty_count'),
        'obsolete_mission_action_count': contract.get('obsolete_mission_action_count'),
        'archives': progress.get('archives'),
    }


report = {'design': 'one persistent 15-object mission with all interruption, session, revision and replacement events',
          'method_comparison': 'native PAOS file memory vs PAOS with TaskMemory; identical per-seed task, scene, executor and budgets',
          'oracle_role': 'physical execution feasibility only, never memory evidence',
          'seeds': {},
          'interpretation': 'Report checkpoint arrival coverage with accuracy conditional on arrival; execution and provider failures remain separate.'}
for seed, stamp in STAMPS.items():
    roots = {role: BASE / 'mission-v4-compact15-{}-s{}-{}'.format(role, seed, stamp)
             for role in ('reference', 'native', 'memory')}
    row = {role: concise(root) for role, root in roots.items()}
    if row['native']['terminal'] and row['memory']['terminal']:
        matched = compare(roots['native'], roots['memory'])
        row['matched'] = matched['matched']
        row['comparability_checks'] = matched['comparability_checks']
    else:
        row['matched'] = None
    report['seeds'][str(seed)] = row
report['all_pairs_terminal'] = all(
    row['native']['terminal'] and row['memory']['terminal']
    for row in report['seeds'].values())
report['all_pairs_matched'] = (report['all_pairs_terminal']
                               and all(row['matched'] for row in report['seeds'].values()))
print(json.dumps(report, ensure_ascii=False, indent=2))
