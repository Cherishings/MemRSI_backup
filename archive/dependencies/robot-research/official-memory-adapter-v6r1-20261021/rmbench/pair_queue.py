"""Durable assets -> integrity -> real controller smoke -> four paired episodes."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path('/data/stormlab/xi/robot')
CODE = Path(__file__).resolve().parent
COMMON = ROOT / 'official-memory-common-20261017v2'
COMMON_DEPS = ROOT / 'official-memory-common-20261017/deps'
ASSET_CODE = ROOT / 'official-memory-rmbench-20261017'
POLICY = Path('/data/stormlab/xi/paos/results/memrsi-bounded-v2_2-20261015T175555Z/experiment/frozen-policy.json')
ACTOR_PYTHON = '/home/xi/envs/agent/bin/python'
FROZEN_POLICY_SHA256 = 'cb4c8f6485401337dcf4368b2537c997503ff385713b6800c4af8a28a7059b77'


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    os.replace(temporary, path)


def identity(pid):
    return {'pid': pid, 'start_ticks': Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def stop(child):
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import setproctitle
    setproctitle.setproctitle('robot')
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    manifest = [{'task': 'cover_blocks', 'seed': seed, 'arm': arm}
                for seed in [0, 1] for arm in ['native', 'memrsi']]
    with (out / 'queue.lock').open('a') as queue_lock:
        fcntl.flock(queue_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic(out / 'identity.json', dict(identity(os.getpid()), gpu=2, started=time.time()))
        if (out / 'manifest.json').exists():
            assert json.loads((out / 'manifest.json').read_text()) == manifest
        atomic(out / 'manifest.json', manifest)
        atomic(out / 'protocol.json', {'task': 'cover_blocks', 'seeds': [0, 1], 'arms': ['native', 'memrsi'],
            'shared_controller': 'frozen Mem-0 execution module only', 'physical_chunk_steps': 8,
            'total_physical_steps': 'unchanged official environment step_lim', 'max_decisions': 600,
            'physical_failure_retry': False, 'success_retry': False, 'automatic_technical_retry': False,
            'learning_enabled': False, 'existing_learning_budget': '8986/9745; unchanged',
            'memory_policy': str(POLICY), 'memory_policy_sha256': FROZEN_POLICY_SHA256,
            'persistent_memory_tokens': 1024, 'active_resource_units': 12288,
            'image_units_per_camera': 1024, 'max_cameras': 3,
            'logical_model_call_limit': 480, 'all_guidance_and_archive_calls_share_this_limit': True,
            'model_output_tokens_per_call': 2048,
            'visual_adapter_version': 'v2',
            'pre_guidance_archive_reserve_units': 2048,
            'archive_reserve_shared_by_both_arms': True,
            'archive_reserve_is_extra_input_capacity': False,
            'visual_archive_accounting': 'actual pending Event, images, proprio, tools; actual TASK after G',
            'native_archive_and_compaction_algorithms_changed': False,
            'episode_wall_timeout': None, 'network_wait_counts_as_capability_failure': False,
            'instruction_visibility': 'complete public task goal is repeated at every actor decision',
            'memory_scope': 'official historical visual manipulation task; not the earlier cross-session mission trial',
            'scope': 'new paired visual-controller protocol on official RMBench; not Mem0 benchmark scores or previous text-only score'} )
        def progress(phase, **kwargs):
            atomic(out / 'progress.json', dict(phase=phase, updated=time.time(), **kwargs))
        while not (ASSET_CODE / 'assets-ready.json').exists():
            progress('waiting_assets', expected_bytes=19566207620, download_supervisor='local prepare_queue.py')
            time.sleep(30)
        progress('verifying_assets')
        assets = json.loads((ASSET_CODE / 'assets-ready.json').read_text())
        assert assets['status'] == 'ready'
        expected = json.loads((ASSET_CODE / 'download-manifest.json').read_text())['files']
        rows = {row['local_path']: row for row in assets['files']}
        assert set(rows) == {row['local_path'] for row in expected}
        for item in expected:
            row = rows[item['local_path']]
            path = ROOT / 'models/official-memory-rmbench-20261017' / item['local_path']
            assert path.stat().st_size == item['size'] and digest(path) == row['sha256_actual']
            assert not item['sha256'] or row['sha256_actual'] == item['sha256']
        atomic(out / 'assets-verified.json', {'status': 'pass', 'files': len(rows), 'time': time.time()})
        while not (COMMON / 'visual-validation-ready.json').exists():
            progress('waiting_actor_validation')
            time.sleep(30)
        from visual_gate import checked as check_visual
        check_visual(COMMON)
        assert digest(POLICY) == FROZEN_POLICY_SHA256
        env = dict(os.environ, CUDA_VISIBLE_DEVICES='2', ROBOT_GPU='2', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                   LITELLM_LOCAL_MODEL_COST_MAP='True',
                   PYTHONPATH=str(CODE / 'actor-deps') + ':' + str(COMMON_DEPS) + ':' + str(COMMON) + ':' + str(CODE))
        simulator_env = dict(env, MUJOCO_GL='egl', PYNPUT_BACKEND='dummy',
            PATH=str(ROOT / 'envs/rmbench/bin') + ':' + os.environ['PATH'],
            LD_LIBRARY_PATH=str(ROOT / 'envs/twin/lib') + ':' + os.environ.get('LD_LIBRARY_PATH', ''),
            CUDA_HOME=str(ROOT / 'envs/twin'), PYTHONPATH=str(CODE))
        controller_env = dict(env, PYTHONPATH=str(CODE))
        controller = simulator = actor = None
        def spawn(command, log_path, child_env):
            with log_path.open('a') as log:
                return subprocess.Popen(command, env=child_env, stdout=log, stderr=log,
                    stdin=subprocess.DEVNULL, start_new_session=True, pass_fds=(gpu_lock.fileno(),))
        def wait_ready(path, child, limit):
            start = time.monotonic()
            while not path.exists():
                if child.poll() is not None:
                    raise RuntimeError('service_exited_before_ready: ' + str(path))
                if time.monotonic() - start > limit:
                    raise TimeoutError('service_start_timeout: ' + str(path))
                time.sleep(2)
        with Path('/data/stormlab/xi/paos/qwen-deploy/gpt-gpu2-run.lock').open('a') as gpu_lock:
            while True:
                try:
                    fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    used = int(subprocess.check_output(['nvidia-smi', '-i', '2', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).strip())
                    if used <= 1024:
                        break
                    fcntl.flock(gpu_lock, fcntl.LOCK_UN)
                except BlockingIOError:
                    pass
                progress('waiting_gpu', gpu=2)
                time.sleep(15)
            try:
                controller_out = out / 'controller'
                controller_out.mkdir(exist_ok=True)
                # Any existing startup without a clean completion requires inspection.
                if (controller_out / 'started.json').exists():
                    progress('requires_interrupted_attempt_audit', component='controller')
                    return
                atomic(controller_out / 'started.json', {'time': time.time()})
                controller = spawn([str(ROOT / 'envs/rmbench-executor-20261017/bin/robot'), str(CODE / 'controller_server.py'),
                                    '--output', str(controller_out)], controller_out / 'execution.log', controller_env)
                progress('loading_frozen_controller', child=identity(controller.pid))
                wait_ready(controller_out / 'controller-ready.json', controller, 1200)
                smoke = out / 'controller-smoke'
                smoke.mkdir(exist_ok=True)
                simulator = spawn([str(ROOT / 'envs/rmbench/bin/robot'), str(CODE / 'bootstrap.py'), str(CODE / 'simulator_server.py'),
                                   '--seed', '913', '--output', str(smoke / 'simulator'), '--smoke'], smoke / 'simulator.log', simulator_env)
                progress('controller_smoke', child=identity(simulator.pid), controller=identity(controller.pid))
                wait_ready(smoke / 'simulator/simulator-ready.json', simulator, 300)
                child = spawn([str(ROOT / 'envs/rmbench-executor-20261017/bin/robot'), str(CODE / 'controller_smoke.py'),
                               '--output', str(smoke / 'result.json')], smoke / 'smoke.log', controller_env)
                try:
                    rc = child.wait(timeout=600)
                finally:
                    stop(child)
                assert rc == 0 and json.loads((smoke / 'result.json').read_text())['status'] == 'pass'
                simulator.wait(timeout=30)
                simulator = None
                completed = []
                for index, item in enumerate(manifest):
                    check_visual(COMMON)
                    assert digest(POLICY) == FROZEN_POLICY_SHA256
                    case = out / f'case-{index:03d}'
                    case.mkdir(exist_ok=True)
                    if (case / 'result.json').exists():
                        result = json.loads((case / 'result.json').read_text())
                        completed.append(result)
                        if result['status'] in {'technical_failure', 'unclassified_failure'}:
                            progress('technical_failure_needs_diagnosis', index=index)
                            return
                        continue
                    if (case / 'started.json').exists():
                        progress('requires_interrupted_attempt_audit', index=index)
                        return
                    atomic(case / 'started.json', dict(item, attempt=1, time=time.time()))
                    simulator = spawn([str(ROOT / 'envs/rmbench/bin/robot'), str(CODE / 'bootstrap.py'), str(CODE / 'simulator_server.py'),
                                       '--seed', str(item['seed']), '--output', str(case / 'simulator')], case / 'simulator.log', simulator_env)
                    progress('starting_episode', index=index, **item, simulator=identity(simulator.pid), controller=identity(controller.pid))
                    wait_ready(case / 'simulator/simulator-ready.json', simulator, 300)
                    actor = spawn([ACTOR_PYTHON, str(CODE / 'pair_episode.py'), '--arm', item['arm'], '--seed', str(item['seed']),
                                   '--policy', str(POLICY), '--output', str(case), '--simulator-output', str(case / 'simulator')], case / 'actor.log', env)
                    progress('running_pair_episode', index=index, **item, actor=identity(actor.pid), simulator=identity(simulator.pid), controller=identity(controller.pid))
                    # Frozen provider budgets bound active work; its WaitClock pauses
                    # transparently on outages without resetting this same attempt.
                    actor.wait()
                    stop(simulator)
                    simulator = None
                    if not (case / 'result.json').exists():
                        atomic(case / 'result.json', dict(item, status='technical_failure', error='actor_exit_without_result', exit_code=actor.returncode))
                    result = json.loads((case / 'result.json').read_text())
                    completed.append(result)
                    atomic(out / 'rows.json', completed)
                    if result['status'] in {'technical_failure', 'unclassified_failure'}:
                        progress('technical_failure_needs_diagnosis', index=index)
                        return
                progress('complete', terminal=len(completed), success=sum(row['status'] == 'success' for row in completed))
            except Exception as error:
                progress('technical_failure_needs_diagnosis', error_type=type(error).__name__, error=str(error)[:500])
            finally:
                stop(actor)
                stop(simulator)
                stop(controller)


if __name__ == '__main__':
    main()
