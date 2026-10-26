"""Sixty-four actual steps, zero LLM calls: execution-interface qualification only."""
import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROBOT = Path('/data/stormlab/xi/robot')
CODE = Path(__file__).resolve().parent
BENCH = CODE / 'rmbench'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(pid):
    return {'pid': pid, 'start_ticks': Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()[19]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import setproctitle
    setproctitle.setproctitle('robot')
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {str(p.relative_to(BENCH)): sha(p) for p in sorted(BENCH.glob('*.py'))}
    overlay = CODE / 'executor-deps'
    evidence = dict(scope='engineering interface qualification; not benchmark performance',
                    status='starting', gpu=0, model_logical_calls=0, learning_calls=0,
                    source_hashes=sources, overlay_manifest_sha256=sha(overlay / 'overlay-manifest.json'),
                    started=time.time(), driver=identity(os.getpid()))
    (args.output / 'started.json').write_text(json.dumps(evidence, indent=2))
    sys.path.insert(0, str(BENCH))
    from rpc_client import post, predict, observe_step
    controller = simulator = None
    receipts = []

    def save():
        (args.output / 'progress.json').write_text(json.dumps(dict(evidence, receipts=receipts, updated=time.time()), indent=2))

    def launch(command, environment, name, lock):
        with (args.output / (name + '.private.log')).open('a') as log:
            child = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=True, pass_fds=(lock.fileno(),))
        evidence[name] = identity(child.pid)
        save()
        return child

    def ready(path, child, limit):
        started = time.monotonic()
        while not path.exists():
            if child.poll() is not None:
                raise RuntimeError('child_exited_before_ready')
            if time.monotonic() - started > limit:
                raise RuntimeError('child_ready_timeout')
            time.sleep(2)

    def stop(child):
        if child is None or child.poll() is not None:
            return
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()

    with (ROBOT.parent / 'paos/qwen-deploy/gpt-gpu0-run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            used = int(subprocess.check_output(['nvidia-smi', '-i', '0', '--query-gpu=memory.used',
                '--format=csv,noheader,nounits'], text=True).strip())
            if used > 1024:
                raise RuntimeError('gpu0_occupied_by_existing_work')
            evidence['gpu_memory_before_mib'] = used
            common_env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', ROBOT_GPU='0',
                OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', HF_HUB_OFFLINE='1',
                HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
            controller_env = dict(common_env, PYTHONPATH=str(overlay) + ':' + str(BENCH))
            simulator_env = dict(common_env, PYTHONPATH=str(BENCH), MUJOCO_GL='egl',
                PYNPUT_BACKEND='dummy', PATH=str(ROBOT / 'envs/rmbench/bin') + ':' + os.environ['PATH'],
                LD_LIBRARY_PATH=str(ROBOT / 'envs/twin/lib'), CUDA_HOME=str(ROBOT / 'envs/twin'))
            controller = launch([str(ROBOT / 'envs/rmbench-executor-20261017/bin/robot'),
                str(BENCH / 'controller_server.py'), '--port', '19580', '--output',
                str(args.output / 'controller')], controller_env, 'controller', lock)
            ready(args.output / 'controller/controller-ready.json', controller, 600)
            evidence['status'] = 'controller_ready'; save()
            simulator = launch([str(ROBOT / 'envs/rmbench/bin/robot'), str(BENCH / 'bootstrap.py'),
                str(BENCH / 'simulator_server.py'), '--seed', '913', '--port', '19581',
                '--output', str(args.output / 'simulator')], simulator_env, 'simulator', lock)
            ready(args.output / 'simulator/simulator-ready.json', simulator, 240)
            public = post(19581, 'observe', {})['public']
            instruction = public['instruction']
            assert len(public['proprio']['joint_action']) == 14
            post(19580, 'reset', {'episode_seed': 913})
            first = predict(19580, public, instruction)
            post(19580, 'reset', {'episode_seed': 913})
            current = predict(19580, public, instruction)
            a, b = np.asarray(first['actions']), np.asarray(current['actions'])
            assert a.shape == b.shape == (8, 14)
            assert np.isfinite(a).all() and np.isfinite(b).all()
            assert np.allclose(a, b, atol=1e-6, rtol=1e-6), 'seed_reset_reproducibility_failed'
            evidence.update(status='executing_real_steps', reproducible_reset=True,
                            controller_identity=current['controller'], first_action_shape=list(a.shape))
            save()
            queue = list(current['actions'])
            while len(receipts) < 64:
                if not queue:
                    current = predict(19580, public, instruction)
                    queue = list(current['actions'])
                before = public['steps']
                result = post(19581, 'step', {'actions': [queue.pop(0)]})
                public = result['public']
                assert public['steps'] == before + 1, 'physical_step_increment_mismatch'
                receipt = observe_step(19580, public)
                assert receipt['executed_steps'] == len(receipts) + 1
                assert receipt['observation_updates'] == 1 + receipt['executed_steps'] + receipt['semantic_resets']
                receipts.append(dict(step=public['steps'], **receipt))
                save()
                if receipt['boundary_ready']:
                    queue = []
                if result['evaluator']['done'] and len(receipts) < 64:
                    raise RuntimeError('native_terminal_before_64_step_qualification')
            post(19581, 'close', {})
            score = json.loads((args.output / 'simulator/result.json').read_text())
            assert score['steps'] == 64 and isinstance(score['official_check_success'], bool)
            assert sources == {str(p.relative_to(BENCH)): sha(p) for p in sorted(BENCH.glob('*.py'))}, 'source_changed_during_qualification'
            evidence.update(status='pass', executed_steps=64, observation_receipts=len(receipts),
                observation_updates=receipts[-1]['observation_updates'],
                semantic_resets=receipts[-1]['semantic_resets'],
                scorer_available=True, scorer_status=score['status'],
                official_success_at_truncation=score['official_check_success'],
                qualification_is_performance_result=False)
        except Exception as error:
            evidence.update(status='technical_qualification_failed', error_type=type(error).__name__,
                            error_code=str(error)[:120])
            try:
                if simulator and simulator.poll() is None:
                    post(19581, 'close', {})
            except Exception:
                pass
        finally:
            stop(simulator); stop(controller)
            evidence.update(finished=time.time(), receipts=receipts)
            (args.output / 'result.json').write_text(json.dumps(evidence, indent=2))
            print(json.dumps({k: evidence[k] for k in ('status', 'executed_steps', 'observation_receipts',
                'observation_updates', 'error_type', 'error_code', 'model_logical_calls') if k in evidence}))


if __name__ == '__main__':
    main()
