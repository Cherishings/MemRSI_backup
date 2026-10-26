"""Wait for old coordinator AND surviving workers before admitting the learner.

The predecessor did not participate in the new per-request model lease. Its
worker identities remain a dependency even if its coordinator dies. Admission
failures become the physical queue's structured failure signal.
"""
import argparse
import json
import os
import time
from pathlib import Path
from run_queue import identity, dump


def alive(record):
    try:
        return (identity(int(record['pid']))['start_ticks'] == str(record['start_ticks'])
                and Path('/proc/%d/stat' % int(record['pid'])).read_text()
                .rsplit(')', 1)[1].split()[0] != 'Z')
    except (FileNotFoundError, ProcessLookupError):
        return False


def identities(value):
    """PID plus kernel start ticks identifies a process; PID alone is not enough."""
    if isinstance(value, dict):
        if 'pid' in value and 'start_ticks' in value:
            yield {'pid': int(value['pid']), 'start_ticks': str(value['start_ticks'])}
        else:
            for child in value.values():
                yield from identities(child)
    elif isinstance(value, list):
        for child in value:
            yield from identities(child)


def previous_state(source):
    source = Path(source)
    coordinator = json.loads((source / 'coordinator.json').read_text())
    progress_path = source / 'progress.json'
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
    records = list(identities(coordinator)) + list(identities(progress.get('active', {})))
    for path in sorted(source.glob('active-gpu*.json')):
        records.extend(identities(json.loads(path.read_text())))
    unique = {(r['pid'], r['start_ticks']): r for r in records}
    return {'live_processes': [r for r in unique.values() if alive(r)],
            'status': progress.get('status'), 'terminal': progress.get('terminal'),
            'planned': progress.get('planned')}


def wait_previous(source, status_path, *, wait_seconds=7200, poll_seconds=10,
                  quiet_seconds=1):
    deadline = time.monotonic() + wait_seconds
    while True:
        state = previous_state(source)
        if not state['live_processes']:
            # Re-read after a quiet interval: the coordinator's final atomic
            # active-worker update may have raced the first snapshot.
            time.sleep(quiet_seconds)
            state = previous_state(source)
            if not state['live_processes']:
                terminal, planned = state['terminal'], state['planned']
                if state['status'] != 'completed' or (
                    isinstance(terminal, int) and isinstance(planned, int) and terminal < planned):
                    raise RuntimeError('previous_queue_incomplete_without_live_coordinator')
                return
        dump(status_path, {'status': 'waiting_previous_model_users',
             'source': str(source), **state, 'updated_unix': time.time()})
        if time.monotonic() >= deadline:
            raise RuntimeError('admission_wait_budget_exhausted')
        time.sleep(poll_seconds)


def main(a):
    status = Path(a.status)
    failure = Path(a.failure) if getattr(a, 'failure', None) else status.parent / 'evolution/failure.json'
    status.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not a.command:
            raise RuntimeError('admission_command_missing')
        wait_previous(a.source, status, wait_seconds=getattr(a, 'wait_seconds', 7200))
        dump(status, {'status': 'admitted', 'source': str(a.source), 'updated_unix': time.time()})
        os.execv(a.command[0], a.command)
    except Exception as exc:
        safe = {'admission_command_missing', 'admission_wait_budget_exhausted',
                'previous_queue_incomplete_without_live_coordinator'}
        code = str(exc) if str(exc) in safe else 'admission_dependency_or_exec_failure'
        record = {'status': 'failed', 'stage': 'admission', 'code': code,
                  'type': type(exc).__name__, 'source': str(a.source), 'updated_unix': time.time()}
        dump(status, record)
        failure.parent.mkdir(parents=True, exist_ok=True)
        dump(failure, record)
        raise RuntimeError(code) from None


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True)
    p.add_argument('--status', required=True)
    p.add_argument('--failure')
    p.add_argument('--wait-seconds', type=float, default=7200)
    p.add_argument('command', nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.command and args.command[0] == '--':
        args.command = args.command[1:]
    main(args)
