"""Pinned public artifacts only; no implicit Hugging Face credentials."""
import concurrent.futures
import ctypes
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / 'outputs/official-memory-rmbench-20261017'
REMOTE = '/data/stormlab/xi/robot/models/official-memory-rmbench-20261017'
GUARD = threading.Lock()


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    os.replace(temporary, path)


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def download(item):
    relative = Path(item['local_path'])
    destination = BASE / 'downloads' / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.partial')
    status_path = BASE / 'download-progress' / (str(relative).replace('/', '--') + '.json')
    status_path.parent.mkdir(exist_ok=True)
    expected = item.get('sha256')
    report = dict(item, phase='downloading', updated=time.time())
    if destination.exists() and destination.stat().st_size == item['size']:
        if not expected or sha256(destination) == expected:
            report.update(phase='downloaded', bytes=item['size'])
    if report['phase'] != 'downloaded':
        for attempt in range(1, 7):
            offset = partial.stat().st_size if partial.exists() else 0
            try:
                request = urllib.request.Request(item['url'], headers={'Range': f'bytes={offset}-'} if offset else {})
                with urllib.request.urlopen(request, timeout=90) as response:
                    if offset and response.status != 206:
                        offset = 0
                    mode = 'ab' if offset else 'wb'
                    with partial.open(mode) as handle:
                        last = 0
                        while chunk := response.read(1024 * 1024):
                            handle.write(chunk)
                            offset += len(chunk)
                            if time.time() - last > 3:
                                report.update(bytes=offset, attempt=attempt, updated=time.time())
                                atomic(status_path, report)
                                last = time.time()
                assert partial.stat().st_size == item['size'], 'size mismatch'
                digest = sha256(partial)
                assert not expected or digest == expected, 'sha256 mismatch'
                os.replace(partial, destination)
                report.update(phase='downloaded', bytes=item['size'], sha256_actual=digest)
                break
            except Exception as error:
                report.update(phase='download_retry', error_type=type(error).__name__, attempt=attempt, bytes=offset)
                atomic(status_path, report)
                if attempt == 6:
                    raise
                time.sleep(min(10 * attempt, 60))
    report.update(phase='uploading', updated=time.time())
    atomic(status_path, report)
    remote_path = REMOTE + '/' + relative.as_posix()
    subprocess.run(['ssh', 'xi', 'mkdir', '-p', str(Path(remote_path).parent)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['scp', '-q', str(destination), 'xi:' + remote_path], check=True)
    remote_hash = subprocess.check_output(['ssh', 'xi', 'sha256sum', remote_path], text=True).split()[0]
    local_hash = report.get('sha256_actual') or sha256(destination)
    assert remote_hash == local_hash
    report.update(phase='ready_remote', sha256_actual=local_hash, remote_path=remote_path, updated=time.time())
    atomic(status_path, report)
    return report


def main():
    ctypes.CDLL(None).prctl(15, b'robot', 0, 0, 0)
    manifest = json.loads((BASE / 'download-manifest.json').read_text())
    atomic(BASE / 'download-identity.json', {'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19], 'started': time.time()})
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(download, manifest['files']))
    atomic(BASE / 'download-result.json', {'status': 'ready', 'files': results, 'finished': time.time()})


if __name__ == '__main__':
    main()
