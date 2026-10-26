#!/usr/bin/env python3
"""Print safe, compact progress for the active v6 experiment batches."""
import json
from pathlib import Path


BASE = Path('/data/stormlab/xi/paos/qwen-deploy')
BATCHES = (
    ('main', 'latest-native-long-workflow-v6.txt', 'scheduler-v2-identity.json'),
    ('final_grasp', 'latest-native-long-workflow-v6-physical.txt', 'queue-identity.json'),
    ('grasp_skill', 'latest-butter-skill-v6-v2.txt', 'probe-identity.json'),
)


def live(identity):
    if not identity.exists():
        return False
    value = json.loads(identity.read_text())
    proc = Path('/proc') / str(value['pid']) / 'stat'
    if not proc.exists():
        return False
    actual = int(proc.read_text().rsplit(') ', 1)[1].split()[19])
    return actual == int(value['start_ticks'])


for label, pointer, identity_name in BATCHES:
    root = Path((BASE / pointer).read_text().strip())
    progress = json.loads((root / 'progress.json').read_text())
    keys = ('stage', 'planned_total', 'terminal_total', 'planned', 'terminal',
            'terminal_by_stage', 'hidden_probe_reached', 'hidden_probe_correct',
            'hidden_pair_both_correct', 'hidden_pair_scene_matched',
            'native_full_success', 'reached', 'correct', 'pair_scene_matched',
            'pair_both_correct', 'physical_final_attempted',
            'physical_final_success', 'failure_domains')
    result = {'batch': label, 'path': str(root),
              'supervisor_alive': live(root / identity_name)}
    result.update({key: progress[key] for key in keys if key in progress})
    print(json.dumps(result, ensure_ascii=False))
