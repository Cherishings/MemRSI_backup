"""Idempotent detached queue launch; existing pointers never restart scored cases."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    code = Path(__file__).resolve().parent
    root = Path('/data/stormlab/xi/robot')
    os.umask(0o077)
    with (code / 'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pointer = code / 'latest-pair-queue.json'
        if pointer.exists():
            print(pointer.read_text())
            return
        from visual_gate import checked
        checked(root / 'official-memory-common-20261017v2')
        out = root / 'runs' / ('official-memory-rmbench-paired-r4-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
        out.mkdir()
        with (out / 'coordinator.log').open('w') as log:
            child = subprocess.Popen([str(root / 'envs/rmbench-executor-20261017/bin/robot'), str(code / 'pair_queue.py'), '--output', str(out)],
                                     stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        info = {'pid': child.pid, 'start_ticks': Path(f'/proc/{child.pid}/stat').read_text().rsplit(')', 1)[1].split()[19],
                'output': str(out), 'code': str(code), 'gpu': 2, 'phase_at_launch': 'waiting_assets',
                'scope': 'frozen shared execution controller + PAOS/MemRSI paired visual evaluation; assets pending, no benchmark result yet'}
        pointer.write_text(json.dumps(info, indent=2))
        print(json.dumps(info))


if __name__ == '__main__':
    main()
