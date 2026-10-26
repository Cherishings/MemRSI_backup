"""Launch once; register before releasing children and retain crash-safe leases."""
import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess

from admission_wait import alive, identities
from run_queue import ROOT, BASE, dump, identity, env, stop_group

SOURCE = BASE / 'results/memrsi-mission-stress-v1-20261010T085842Z'
ORDERS = BASE / 'results/memrsi-history-pairs-v1-20261010T074232Z/selected-orders.json'
VERSION = 'memrsi-evidence-v2_2'


def atomic_pointer(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(str(value) + '\n')
    temporary.replace(path)


def pipeline_lease_live(output):
    """Inherited by both coordinators, covering the spawn-to-PID-record gap."""
    path = Path(output) / 'pipeline.lock'
    if not path.exists():
        return False
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True


def previous_activity(output, record):
    records = list(identities(record.get('processes', {})))
    # A dead coordinator can leave worker/policy processes; never restart over them.
    for name in ('physical/coordinator.json', 'physical/progress.json',
                 'physical/policy-gpu0.identity.json', 'physical/policy-gpu1.identity.json'):
        path = Path(output) / name
        if path.exists():
            data = json.loads(path.read_text())
            if name.endswith('progress.json'):
                data = data.get('active', {})
            records.extend(identities(data))
    unique = {(r['pid'], r['start_ticks']): r for r in records}
    return [r for r in unique.values() if alive(r)]


def stop_owned(children):
    for process, record in reversed(children):
        if process.poll() is None:
            # Even if registration failed immediately after Popen, this remains
            # our unreaped child; obtain its identity before signalling it.
            try:
                record = record or identity(process.pid)
                if alive(record):
                    stop_group(process)
            except (FileNotFoundError, ProcessLookupError):
                pass


def main():
    with (BASE / 'qwen-deploy/memrsi-coupled-launch.lock').open('a') as launch_lock:
        fcntl.flock(launch_lock, fcntl.LOCK_EX)
        pointer = BASE / 'qwen-deploy/latest-memrsi-coupled.txt'
        prior = set((BASE / 'results').glob('memrsi-coupled-v*/launch.json')) | set((BASE / 'results').glob('memrsi-evidence-v*/launch.json'))
        if pointer.exists():
            prior.add(Path(pointer.read_text().strip()) / 'launch.json')
        for path in sorted(prior):
            if not path.exists():
                raise RuntimeError('previous_launch_record_missing')
            previous = json.loads(path.read_text())
            activity = previous_activity(path.parent, previous)
            if pipeline_lease_live(path.parent) or activity:
                print(json.dumps({'status': 'already_running', 'result': str(path.parent),
                                  'live_processes': activity}))
                return
            # Never reset an unfinished same-version trial budget in a new directory.
            # A failed launch cleaned its children and is a pre-experiment exception.
            if previous.get('version') == VERSION and previous.get('status') != 'launch_failed':
                physical = path.parent / 'physical/report.json'
                evolution = path.parent / 'evolution/progress.json'
                completed = (physical.exists() and evolution.exists()
                    and json.loads(physical.read_text()).get('status') == 'completed'
                    and json.loads(evolution.read_text()).get('status') == 'completed')
                if not completed:
                    print(json.dumps({'status': 'existing_incomplete_pipeline', 'result': str(path.parent),
                                      'action': 'inspect original results; automatic restart prohibited'}))
                    return
        proof = json.loads((ROOT / 'pristine-core-manifest.json').read_text())
        mismatches = [name for name, expected in proof['core_sha256'].items()
                      if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected]
        if mismatches or proof['mismatches']:
            raise RuntimeError('pristine_source_mismatch')
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out = BASE / 'results' / (VERSION + '-' + now)
        out.mkdir(exist_ok=False)
        dump(out / 'pristine-core-manifest.json', proof)
        dump(out / 'code-manifest.json', {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in ROOT.rglob('*') if path.is_file() and '__pycache__' not in path.parts and 'PhyAgentOS' not in path.parts})
        python = '/home/xi/envs/agent/bin/python'
        commands = {
            'evolution': [python, str(ROOT / 'admission_wait.py'), '--source', str(SOURCE),
                '--status', str(out / 'evolution-admission.json'),
                '--failure', str(out / 'evolution/failure.json'), '--',
                python, str(ROOT / 'evolution.py'), '--source', str(SOURCE), '--output', str(out / 'evolution')],
            'physical': [python, str(ROOT / 'physical_queue.py'), '--output', str(out / 'physical'),
                '--orders', str(ORDERS), '--base-policy', str(ROOT / 'configs/base-policy.json'),
                '--evolution-policy', str(out / 'evolution/final-policy.json')]}
        record = {'version': VERSION, 'status': 'launching', 'result': str(out), 'code': str(ROOT),
            'source': str(SOURCE), 'processes': {}, 'gpus': [0, 1], 'model': 'gpt-5.6-luna',
            'physical_planned': 48, 'native_fixed_first': 32, 'evolved_after_freeze': 16,
            'supersedes_interface_version': '/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/portable-runtime-20261023/paos/results/memrsi-evidence-v2_1-20261010T124454Z',
            'all_new_model_calls_serialized': True, 'wait_previous_noncooperating_queue': True}
        children = []
        # Discoverable record and atomic pointer precede Popen. Child inheritance
        # covers a launcher crash before its next atomic PID record is written.
        with (out / 'pipeline.lock').open('a') as pipeline_lease:
            fcntl.flock(pipeline_lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            dump(out / 'launch.json', record)
            atomic_pointer(pointer, out)
            try:
                for name, command in commands.items():
                    with (out / (name + '.log')).open('xb') as stream:
                        child = subprocess.Popen(command, cwd=ROOT, env=env(0), stdin=subprocess.DEVNULL,
                            stdout=stream, stderr=stream, start_new_session=True,
                            pass_fds=(pipeline_lease.fileno(),))
                    children.append((child, None))
                    child_identity = identity(child.pid)
                    children[-1] = (child, child_identity)
                    record['processes'][name] = child_identity
                    dump(out / 'launch.json', record)
                record['status'] = 'running'
                dump(out / 'launch.json', record)
            except BaseException as exc:
                stop_owned(children)
                record.update(status='launch_failed', error_type=type(exc).__name__,
                              error_code='launch_registration_or_spawn_failure')
                dump(out / 'launch.json', record)
                raise RuntimeError('launch_registration_or_spawn_failure') from None
        # Closing only the parent fd preserves the lease in live coordinators.
        # Explicit LOCK_UN here would incorrectly unlock their shared description.
        print(json.dumps(record))


if __name__ == '__main__':
    main()
