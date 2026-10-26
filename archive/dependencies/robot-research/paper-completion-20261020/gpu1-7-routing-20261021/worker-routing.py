"""User-authorized GPU routing only; registered worker and method files stay frozen."""
import hashlib,json,sys
from pathlib import Path
ORIGINAL=Path('/data/stormlab/xi/robot/paper-completion-20261020/guidance-diagnostic-20261021/worker.py')
OLD='choices=[4,7]'
NEW='choices=[1,2,3,4,7]'
def routed_source(source):
    if source.count(OLD)!=1:raise RuntimeError('unexpected_original_gpu_cli')
    return source.replace(OLD,NEW,1)
def main():
    root=Path('/data/stormlab/xi/robot/runs/paper-completion-20261020/guidance-diagnostic-20261021')
    manifest=json.loads((root/'manifest.json').read_text())
    raw=ORIGINAL.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest['code_sha256']['worker.py']:raise RuntimeError('registered_worker_changed')
    source=routed_source(raw.decode())
    core=Path(manifest['core'])
    dependency=core/'memory_policy.py'
    expected=manifest['source_identity']['files']['core']['memory_policy.py']
    if hashlib.sha256(dependency.read_bytes()).hexdigest()!=expected:raise RuntimeError('registered_dependency_changed')
    sys.path.insert(0,str(core))
    sys.path.insert(0,str(ORIGINAL.parent))
    exec(compile(source,str(ORIGINAL),'exec'),{'__name__':'__main__','__file__':str(ORIGINAL)})
if __name__=='__main__':main()
