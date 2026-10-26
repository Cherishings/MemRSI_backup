"""New-server path/device wiring; frozen physical execution code is not edited.

Call install_agent_runtime() before importing feedback_workflow. Every lane sets
PAOS_LANE_GPU to its physical GPU index. Physics uses the original NativeWorld,
and policy uses the original paired-sampling implementation.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
DEFAULT_MIGRATION = '/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022'


class Paths:
    def __init__(self):
        self.migration = Path(os.environ.get('PAOS_MIGRATION_ROOT', DEFAULT_MIGRATION))
        self.source = Path(os.environ.get('PAOS_LIBERO_SOURCE', str(self.migration / 'portable-runtime-20261023/paos/worktrees/memrsi-bounded-v2_2')))
        self.core = Path(os.environ.get('PAOS_CORE_ROOT', str(self.migration / 'PhyAgentOS-core')))
        self.openpi = self.migration / 'openpi'
        self.checkpoint = Path(os.environ.get('PAOS_POLICY_CHECKPOINT', str(self.migration / 'models/pi05_libero')))
        self.libero_config = self.migration / 'runtime-config/libero'
        self.agent_python = self.migration / 'conda-envs/paos-agent/bin/python'
        self.policy_python = self.migration / 'conda-envs/paos-policy/bin/python'
        self.physics_python = self.migration / 'conda-envs/paos-libero-py38/bin/python'
        self.official = self.openpi / 'examples/libero/main.py'

    def pythonpath(self):
        return [str(HERE), str(self.source), str(self.core),
                str(self.openpi / 'src'), str(self.openpi / 'packages/openpi-client/src'),
                str(self.openpi / 'third_party/libero')]

    def validate(self):
        required = dict(source=self.source, core=self.core / 'PhyAgentOS',
                        checkpoint_params=self.checkpoint / 'params',
                        checkpoint_assets=self.checkpoint / 'assets',
                        libero_config=self.libero_config / 'config.yaml',
                        agent_python=self.agent_python, policy_python=self.policy_python,
                        physics_python=self.physics_python, official=self.official)
        for name in ('native_world.py', 'check_case.py', 'world_client.py',
                     'feedback_workflow.py', 'paired_sampling.py', 'serve_paired_policy.py',
                     'retry_recovery.py', 'runtime_config.py'):
            required[name] = self.source / name
        missing = {name: str(path) for name, path in required.items() if not path.exists()}
        if missing:
            raise RuntimeError('missing_runtime_paths: ' + json.dumps(missing, sort_keys=True))
        return {name: str(path) for name, path in required.items()}


def lane_env(gpu, role='agent'):
    """Isolate policy CUDA; EGL is explicitly indexed in the physical namespace."""
    if role not in ('agent', 'physics', 'policy'):
        raise ValueError('invalid_runtime_role')
    gpu = int(gpu)
    if gpu < 0:
        raise ValueError('invalid_gpu_index')
    paths = Paths()
    result = dict(os.environ, PAOS_LANE_GPU=str(gpu),
                  LIBERO_CONFIG_PATH=str(paths.libero_config),
                  XLA_PYTHON_CLIENT_PREALLOCATE='false',
                  OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', MKL_NUM_THREADS='4',
                  PYTHONUNBUFFERED='1', LITELLM_LOCAL_MODEL_COST_MAP='True')
    result['PYTHONPATH'] = os.pathsep.join(paths.pythonpath())
    if role == 'physics':
        # EGL IDs enumerate physical devices; do not also remap CUDA IDs here.
        result.pop('CUDA_VISIBLE_DEVICES', None)
        result.update(MUJOCO_GL='egl', PYOPENGL_PLATFORM='egl',
                      MUJOCO_EGL_DEVICE_ID=str(gpu))
    else:
        result['CUDA_VISIBLE_DEVICES'] = str(gpu)
    return result


def policy_command(port):
    paths = Paths()
    return [str(paths.policy_python), '-u', str(HERE / 'policy_entry.py'),
            '--port', str(int(port)), '--checkpoint', str(paths.checkpoint)]


def workflow_command(arguments, workflow='feedback_workflow.py'):
    paths = Paths()
    return [str(paths.agent_python), '-u', str(HERE / 'agent_entry.py'),
            '--workflow', workflow, '--'] + list(arguments)


class MigratedWorld:
    """Same request protocol/close behavior as world_client.World, correct Python."""
    def __init__(self, out, port, init, order):
        paths = Paths()
        out = Path(out)
        out.mkdir(parents=True, exist_ok=False)
        self.log = (out / 'simulation.log').open('w')
        gpu = int(os.environ['PAOS_LANE_GPU'])
        try:
            self.p = subprocess.Popen(
                [str(paths.physics_python), '-u', str(HERE / 'native_world_entry.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                text=True, bufsize=1, env=lane_env(gpu, 'physics'))
        except BaseException:
            self.log.close()
            raise
        try:
            self.initial = self.send(op='initialize', output=str(out / 'physical'),
                                     port=port, init=init,
                                     suite=order.get('benchmark', 'libero_90'),
                                     task_id=order['task_id'], task_name=order['task_name'])
        except BaseException:
            self.close(force=True)
            raise

    def send(self, **req):
        self.p.stdin.write(json.dumps(req) + '\n')
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError('physics_worker_exited')
        response = json.loads(line)
        if not response['ok']:
            raise RuntimeError('physics_' + response.get('error_type', 'error'))
        return response['result']

    def close(self, force=False):
        if self.p.poll() is None:
            try:
                if force:
                    self.p.terminate()
                else:
                    self.send(op='close')
                self.p.wait(timeout=20)
            except Exception:
                self.p.kill()
                self.p.wait()
        self.log.close()


def install_agent_runtime():
    """Importable hook; call before feedback_workflow/twenty_agent imports."""
    paths = Paths()
    for path in reversed(paths.pythonpath()):
        if path not in sys.path:
            sys.path.insert(0, path)
    os.environ['LIBERO_CONFIG_PATH'] = str(paths.libero_config)
    import runtime_config
    runtime_config.GATEWAY_URL = os.environ.get('PAOS_GATEWAY_URL', 'http://127.0.0.1:19099/v1')
    import world_client
    world_client.World = MigratedWorld
    # model_provider owns its own URL constant; do not import the model provider
    # just to install wiring (and never read a credential in this hook).
    return paths


def install_physics_runtime():
    paths = Paths()
    for path in reversed(paths.pythonpath()):
        if path not in sys.path:
            sys.path.insert(0, path)
    gpu = int(os.environ['PAOS_LANE_GPU'])
    os.environ.update(lane_env(gpu, 'physics'))
    os.environ.pop('CUDA_VISIBLE_DEVICES', None)
    import check_case
    check_case.OFFICIAL = paths.official
    original_load = check_case.load_official

    def load_official_on_device():
        module = original_load()
        original_constructor = module.OffScreenRenderEnv

        def offscreen_on_device(*args, **kwargs):
            kwargs['render_gpu_device_id'] = gpu
            return original_constructor(*args, **kwargs)

        # _get_libero_env still constructs/seeds the official environment; the
        # only changed constructor keyword selects the rendering device.
        module.OffScreenRenderEnv = offscreen_on_device
        return module

    check_case.load_official = load_official_on_device
    return paths


def manifest():
    paths = Paths()
    checked = paths.validate()
    sources = {name: hashlib.sha256((paths.source / name).read_bytes()).hexdigest()
               for name in ('native_world.py', 'retry_recovery.py', 'paired_sampling.py',
                            'feedback_workflow.py', 'serve_paired_policy.py')}
    return {'paths': checked, 'source_sha256': sources,
            'wiring_only': True, 'native_execution_source_unchanged': True,
            'policy_configuration': 'pi05_libero',
            'paired_sampling': 'original paired_sampling.PairedPolicy',
            'gateway_url': os.environ.get('PAOS_GATEWAY_URL', 'http://127.0.0.1:19099/v1')}


if __name__ == '__main__':
    print(json.dumps(manifest(), indent=2, ensure_ascii=False))
