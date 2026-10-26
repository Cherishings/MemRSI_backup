#!/usr/bin/env python3
"""Read-only, credential-safe progress snapshot for the native PAOS v6 runs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request

DEPLOY = Path('/data/stormlab/xi/paos/qwen-deploy')
POINTERS = {
    'qwen_v6': 'latest-native-long-workflow-v6.txt',
    'physical_final': 'latest-native-long-workflow-v6-physical.txt',
    'gpt_hidden': 'latest-native-long-workflow-v6-gpt.txt',
    'gpt_controls_gpu4': 'latest-native-long-workflow-v6-gpt-controls.txt',
    'parallel_manager': 'latest-native-long-workflow-v6-parallel-lease.txt',
}
FIELDS = ('stage', 'planned_total', 'terminal_total', 'planned', 'terminal',
          'terminal_by_stage', 'hidden_probe_reached', 'hidden_probe_correct',
          'hidden_pair_both_correct', 'hidden_pair_scene_matched',
          'native_full_success', 'reached', 'correct', 'pair_scene_matched',
          'pair_both_correct', 'physical_final_attempted',
          'physical_final_success', 'failure_domains', 'gpus', 'slots_per_gpu')


def alive(record):
    if not record:
        return False
    stat = Path('/proc') / str(record['pid']) / 'stat'
    if not stat.exists():
        return False
    fields = stat.read_text().rsplit(') ', 1)[1].split()
    return fields[0] != 'Z' and int(fields[19]) == int(record['start_ticks'])


def load(path):
    return json.loads(path.read_text()) if path.exists() else {}


manager_file = DEPLOY / POINTERS['parallel_manager']
manager = Path(manager_file.read_text().strip()) if manager_file.exists() else None
children = load(manager / 'children.json') if manager else {}
for label, pointer in POINTERS.items():
    pointer_file = DEPLOY / pointer
    if not pointer_file.exists():
        continue
    root = Path(pointer_file.read_text().strip())
    progress = load(root / 'progress.json')
    summary = {'time_utc': datetime.now(timezone.utc).isoformat(),
               'batch': label, 'path': str(root)}
    summary.update({key: progress[key] for key in FIELDS if key in progress})
    if label == 'parallel_manager':
        summary['manager_alive'] = alive(load(root / 'manager-identity.json'))
        summary['scheduler_alive'] = {name: alive(identity)
                                      for name, identity in children.items()}
    elif label == 'qwen_v6':
        summary['scheduler_alive'] = alive(children.get('main'))
    elif label == 'physical_final':
        summary['scheduler_alive'] = alive(children.get('hybrid'))
    elif label == 'gpt_hidden':
        summary['scheduler_alive'] = alive(children.get('gpt'))
    elif label == 'gpt_controls_gpu4':
        summary['scheduler_alive'] = alive(load(root / 'queue-identity.json'))
    print(json.dumps(summary, ensure_ascii=False))

try:
    with urllib.request.urlopen('http://127.0.0.1:19080/health', timeout=2) as response:
        health = json.load(response)
    print(json.dumps({'gpt_gateway_ok': health.get('ok') is True,
                      'model': health.get('model')}, ensure_ascii=False))
except Exception:
    print(json.dumps({'gpt_gateway_ok': False}, ensure_ascii=False))
