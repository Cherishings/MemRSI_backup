"""Download pinned public files directly from resolved official CDN addresses."""
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

CODE = Path(__file__).resolve().parent
MODEL = Path('/data/stormlab/xi/robot/models/official-memory-rmbench-20261017')


def atomic(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2))
    os.replace(temp, path)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def download(item):
    destination = MODEL / item['local_path']
    destination.parent.mkdir(parents=True, exist_ok=True)
    progress = CODE / 'asset-download' / (item['local_path'].replace('/', '--') + '.json')
    partial = destination.with_name(destination.name + '.partial')
    report = {key: item[key] for key in ['repo', 'revision', 'path', 'local_path', 'size', 'sha256']}
    if destination.exists() and destination.stat().st_size == item['size'] and digest(destination) == item['sha256']:
        report.update(phase='ready_remote', bytes=item['size'], sha256_actual=item['sha256'], remote_path=str(destination))
        atomic(progress, report)
        return report
    for attempt in range(1, 31):
        offset = partial.stat().st_size if partial.exists() else 0
        initial = offset
        started = time.monotonic()
        try:
            urls = json.loads((CODE / 'public-cdn-urls.json').read_text())
            url = urls[item['local_path']]
            request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
            with urllib.request.urlopen(request, timeout=90) as response:
                if offset and response.status != 206:
                    offset = initial = 0
                with partial.open('ab' if offset else 'wb') as handle:
                    last = 0
                    while chunk := response.read(4 * 1024 * 1024):
                        handle.write(chunk)
                        offset += len(chunk)
                        if time.monotonic() - last > 3:
                            report.update(phase='downloading_direct_public_cdn', bytes=offset, attempt=attempt,
                                          bytes_per_second=(offset - initial) / max(time.monotonic() - started, 0.001), updated=time.time())
                            atomic(progress, report)
                            last = time.monotonic()
            assert partial.stat().st_size == item['size'], 'download size mismatch'
            report.update(phase='verifying_sha256', bytes=offset, updated=time.time())
            atomic(progress, report)
            assert digest(partial) == item['sha256'], 'download SHA256 mismatch'
            os.replace(partial, destination)
            report.update(phase='ready_remote', sha256_actual=item['sha256'], remote_path=str(destination), updated=time.time())
            atomic(progress, report)
            return report
        except Exception as error:
            report.update(phase='transport_retry', error_type=type(error).__name__, http_status=getattr(error, 'code', None),
                          bytes=offset, attempt=attempt, updated=time.time())
            atomic(progress, report)
            if isinstance(error, AssertionError) or attempt == 30:
                raise
            time.sleep(30)


def main():
    import setproctitle
    setproctitle.setproctitle('robot')
    os.umask(0o077)
    folder = CODE / 'asset-download'
    folder.mkdir(exist_ok=True)
    with (folder / 'download.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic(folder / 'identity.json', {'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19], 'started': time.time()})
        try:
            manifest = json.loads((CODE / 'download-manifest.json').read_text())
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                rows = list(pool.map(download, manifest['files']))
            atomic(CODE / 'assets-ready.json', {'status': 'ready', 'files': rows, 'finished': time.time(), 'transport': 'public official CDN direct; revision and SHA256 pinned'})
        except Exception as error:
            atomic(folder / 'failure.json', {'status': 'transport_failure', 'error_type': type(error).__name__, 'time': time.time()})
            raise SystemExit(1)


if __name__ == '__main__':
    main()
