#!/usr/bin/env python3
"""Continue GPT visible-cue/history-rescue controls for seeds 10 through 19."""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/data/stormlab/xi/paos/worktrees/native-long-workflow-v6-gpt-20261006')
DEPLOY = Path('/data/stormlab/xi/paos/qwen-deploy')
PYTHON = '/home/xi/envs/agent/bin/python'
GPU = 4
SEEDS = tuple(range(10, 20))
CONDITIONS = ('front_butter_final', 'rear_butter_final')
CUES = ('visible', 'rescue')


def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def alive(record):
    stat = Path('/proc') / str(record['pid']) / 'stat'
    if not stat.exists():
        return False
    fields = stat.read_text().rsplit(') ', 1)[1].split()
    return fields[0] != 'Z' and int(fields[19]) == int(record['start_ticks'])


def case_id(seed, condition, cue):
    return 's%02d-%s-gpt-%s_probe' % (seed, condition, cue)


def gateway_ok():
    try:
        with urllib.request.urlopen('http://127.0.0.1:19080/health', timeout=3) as response:
            return json.load(response).get('model') == 'gpt-5.6-luna'
    except Exception:
        return False


def run_case(out, seed, condition, cue):
    case = out / case_id(seed, condition, cue)
    if not case.exists():
        cmd = [PYTHON, str(ROOT / 'scripts/launch_breakfast.py'), 'launch',
               '--output', str(case), '--gpu', str(GPU), '--seed', str(seed),
               '--condition', condition, '--controller', 'paos',
               '--mode', 'fixed_prefix_probe', '--cue', cue,
               '--executor', 'diagnostic_atomic',
               '--api-base', 'http://127.0.0.1:19080/v1',
               '--api-key-file', str(DEPLOY / 'gpt-gateway-token'),
               '--model', 'gpt-5.6-luna', '--policy-port', str(19220 + GPU),
               '--action-steps', '1000', '--max-steps', '36000',
               '--max-actions', '160', '--max-calls', '500',
               '--wall-seconds', '5400']
        launched = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                  text=True, timeout=120, check=True)
        if Path(json.loads(launched.stdout)['output']) != case:
            raise RuntimeError('launcher_output_mismatch')
    owner = case / 'launcher-identity.json'
    while not (case / 'exit-code.txt').exists():
        if not owner.exists() or not alive(json.loads(owner.read_text())):
            return {'case_id': case.name, 'seed': seed, 'condition': condition,
                    'cue': cue, 'status': 'launcher_lost'}
        time.sleep(10)
    file = case / 'episode/result.json'
    result = json.loads(file.read_text()) if file.exists() else {}
    return {'case_id': case.name, 'case': str(case), 'seed': seed,
            'condition': condition, 'cue': cue, 'gpu': GPU,
            'status': result.get('status', 'missing_result'),
            'failure_domain': result.get('failure_domain'),
            'reason': result.get('reason'),
            'probe_reached': result.get('probe_reached'),
            'probe_answer_correct': result.get('probe_answer_correct'),
            'final_scene_hash': result.get('final_scene_hash'),
            'final_cue': result.get('final_cue'),
            'result': str(file) if result else None}


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: run_gpt_controls_gpu4.py OUTPUT')
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files = ('long_mission_contract.py', 'run_breakfast.py',
                 'real_breakfast_worker.py', 'launch_breakfast.py')
        hashes = {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                  for name in files}
        manifest = {'protocol': 'native-paos-gpt-v6-visible-and-rescue-controls-seeds10-19',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'source_hashes': hashes, 'model': 'gpt-5.6-luna',
                    'executor': 'diagnostic_atomic', 'seeds': SEEDS,
                    'conditions': CONDITIONS, 'cues': CUES,
                    'planned': len(SEEDS) * len(CONDITIONS) * len(CUES),
                    'gpu': GPU, 'case_retry_policy': 'never rerun terminal case',
                    'relationship': 'Continuation of the same GPT controls for seeds 10-19. Combine by seed with the existing seeds 0-9 control cohort, never with Qwen.',
                    'prior_gpt_controls': '/data/stormlab/xi/paos/results/native-long-workflow-v6-gpt-controls-20261006T084906Z',
                    'scheduler_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        file = out / 'manifest.json'
        if file.exists():
            if json.loads(file.read_text())['source_hashes'] != hashes:
                raise RuntimeError('frozen_source_mismatch')
        else:
            save(file, manifest)
        (DEPLOY / 'latest-native-long-workflow-v6-gpt-controls-extra.txt').write_text(str(out) + '\n')
        records = json.loads((out / 'progress.json').read_text()).get('records', []) if (out / 'progress.json').exists() else []
        known = {row['case_id'] for row in records}

        def snapshot(stage):
            save(out / 'progress.json', {
                'stage': stage, 'planned': manifest['planned'],
                'terminal': len(records),
                'reached': sum(row.get('probe_reached') is True for row in records),
                'correct': sum(row.get('probe_answer_correct') is True for row in records),
                'records': records})

        first = [(SEEDS[0], condition, cue) for cue in CUES for condition in CONDITIONS]
        rest = [(seed, condition, cue) for cue in CUES for seed in SEEDS
                for condition in CONDITIONS if seed != SEEDS[0]]
        for phase, group in [('first_controls', first), ('running', rest)]:
            for seed, condition, cue in group:
                key = case_id(seed, condition, cue)
                if key in known:
                    continue
                if not gateway_ok():
                    snapshot('gateway_unavailable')
                    return 2
                snapshot(phase)
                try:
                    row = run_case(out, seed, condition, cue)
                except Exception as exc:
                    row = {'case_id': key, 'seed': seed, 'condition': condition,
                           'cue': cue, 'status': 'batch_exception',
                           'exception_type': type(exc).__name__}
                records.append(row)
                known.add(key)
                snapshot(phase)
        snapshot('finished')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
