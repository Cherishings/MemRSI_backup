"""One-shot boundary relay, with identity checks and durable launch intents."""
import argparse
import importlib.util
import os
import subprocess
import time
from pathlib import Path

ROOT = Path('/data/stormlab/xi/robot')
HERE = Path(__file__).resolve().parent

def main():
    p = argparse.ArgumentParser(); p.add_argument('--output', required=True); a = p.parse_args()
    out = Path(a.output)
    spec = importlib.util.spec_from_file_location('cap', ROOT/'paper-supplement-20261018/capacity_robustness.py')
    cap = importlib.util.module_from_spec(spec); spec.loader.exec_module(cap)
    with cap.locked(out/'scheduler.lock', nonblocking=True):
        me = cap.identity(); cap.write(out/'scheduler.json', {'identity': me, 'phase': 'waiting_predecessor'})
        plan = cap.read(out/'relay-plan.json'); manifest = cap.read(out/'manifest.json')
        old = Path(plan['predecessor'])
        def paused(reason, **detail):
            cap.write(out/'relay-paused.json', dict(reason=reason, identity=me, time=time.time(), **detail))
        for name, digest in manifest['code_sha256'].items():
            if cap.file_sha(HERE/name) != digest:
                paused('code_changed'); return
        old_manifest = cap.read(old/'manifest.json')
        if cap.file_sha(old/'manifest.json') != plan['predecessor_manifest_sha256']:
            paused('predecessor_manifest_changed'); return
        if any(out.glob('launch-intent-gpu*.json')):
            paused('existing_launch_intent_requires_audit'); return
        while time.time() < manifest['start_before_epoch']:
            if (old/'blocked.json').exists():
                paused('predecessor_blocked_requires_audit', block=cap.read(old/'blocked.json')); return
            states = {str(g): cap.read(old/f'worker-gpu{g}.json', {}) for g in (4,7)}
            alive = {str(g): cap.alive(plan['predecessor_workers'][str(g)]) for g in (4,7)}
            for g in (4,7):
                st = states[str(g)]
                if st.get('identity') != plan['predecessor_workers'][str(g)]:
                    paused('predecessor_identity_changed', gpu=g); return
                if not alive[str(g)] and st.get('phase') != 'completed':
                    paused('predecessor_exited_without_completed', gpu=g, state=st); return
            missing = [j['key'] for j in old_manifest['jobs'] if not (old/j['key']/'result.json').exists()]
            cap.write(out/'relay-progress.json', {'phase': 'waiting_predecessor', 'identity': me,
                'time': time.time(), 'remaining_predecessor': len(missing), 'alive': alive,
                'new_model_calls': 0, 'reserved_gpu0_3_untouched': True})
            if not any(alive.values()):
                if missing:
                    paused('predecessor_missing_results', missing=missing); return
                claims = cap.read(old/'claims.json', {})
                if any(not (old/k/'result.json').exists() for k in claims):
                    paused('unresolved_predecessor_claim'); return
                invalid = [j['key'] for j in old_manifest['jobs']
                    if cap.read(old/j['key']/'result.json').get('status') == 'technical_failure'
                    or cap.read(old/j['key']/'result.json').get('error_code') == 'unclassified_exception']
                if invalid:
                    paused('predecessor_technical_results_require_audit', cases=invalid); return
                break
            time.sleep(30)
        else:
            paused('registered_start_deadline_reached'); return
        runtime = cap.read(ROOT/'runs/paper-completion-20261020/gpu56-priority/plan.json')
        env = dict(runtime['component_env'])
        # Preserve registered transport and standard shared request/GPU locks.
        assert env.get('MEMRSI_OFFLINE_WAIT') == '1'
        children = {}
        for gpu in (4,7):
            if (out/f'worker-gpu{gpu}.json').exists() or (out/'claims.json').exists():
                # After GPU4 starts it may create claims before GPU7 launch.
                if gpu == 4 or (out/f'worker-gpu{gpu}.json').exists():
                    paused('existing_worker_requires_audit', gpu=gpu); return
            intent = {'gpu': gpu, 'time': time.time(), 'scheduler': me,
                      'command': [runtime['python'], str(HERE/'worker.py'), '--gpu', str(gpu), '--output', str(out)]}
            cap.write(out/f'launch-intent-gpu{gpu}.json', intent)
            with (out/f'worker-gpu{gpu}.log').open('ab') as log:
                child = subprocess.Popen(intent['command'], cwd=str(ROOT), env=env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            children[str(gpu)] = cap.identity(child.pid)
            cap.write(out/'launched.json', {'time': time.time(), 'scheduler': me, 'workers': children})
        cap.write(out/'relay-progress.json', {'phase': 'launched', 'time': time.time(), 'identity': me, 'workers': children})

if __name__ == '__main__':
    main()
