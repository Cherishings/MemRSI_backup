"""Public hook for a lane worker, called before importing feedback_workflow."""
import os
from pathlib import Path
from libero_runtime import (Paths, install_agent_runtime, lane_env, manifest,
                            policy_command, workflow_command)


def configure(gpu, port, core_path=None):
    gpu, port = int(gpu), int(port)
    if gpu < 0 or not 1 <= port <= 65535:
        raise ValueError('invalid_lane_gpu_or_port')
    if core_path is not None:
        core_path = Path(core_path)
        if not (core_path / 'PhyAgentOS').is_dir():
            raise ValueError('core_path_must_contain_PhyAgentOS_package')
        os.environ['PAOS_CORE_ROOT'] = str(core_path)
    os.environ.update(lane_env(gpu, 'agent'))
    os.environ['PAOS_POLICY_PORT'] = str(port)
    paths = install_agent_runtime()
    import model_provider
    model_provider.GATEWAY_URL = os.environ.get('PAOS_GATEWAY_URL', 'http://127.0.0.1:19098/v1')
    return {'gpu': gpu, 'port': port, 'source': str(paths.source),
            'core': str(paths.core), 'physics_python': str(paths.physics_python),
            'gateway_url': model_provider.GATEWAY_URL}


__all__ = ['configure', 'lane_env', 'policy_command', 'workflow_command', 'manifest', 'Paths']
