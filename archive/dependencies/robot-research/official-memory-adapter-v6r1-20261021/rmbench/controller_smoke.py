"""Real frozen-model/simulator wiring check, never an evaluation score."""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import setproctitle
    setproctitle.setproctitle('robot')
    import numpy as np
    from rpc_client import post, predict
    started = time.time()
    public = post(19243, 'observe', {})['public']
    assert len(public['proprio']['joint_action']) == 14
    assert set(public['proprio']) == {'joint_action'}
    post(19242, 'reset', {'episode_seed': 913})
    first = predict(19242, public, public['instruction'])
    post(19242, 'reset', {'episode_seed': 913})
    second = predict(19242, public, public['instruction'])
    assert first['controller'] == second['controller']
    a, b = np.asarray(first['actions']), np.asarray(second['actions'])
    assert a.shape == b.shape == (8, 14) and np.isfinite(a).all()
    assert np.allclose(a, b, atol=1e-6, rtol=1e-6), 'reset did not reproduce same controller action'
    response = post(19243, 'step', {'actions': first['actions']})
    assert response['public']['steps'] > 0
    post(19243, 'close', {})
    result = {'status': 'pass', 'scope': 'real controller/simulator infrastructure smoke; not a score',
              'controller': first['controller'], 'reproducible_reset': True, 'action_shape': list(a.shape),
              'executed_steps': response['public']['steps'], 'started': started, 'finished': time.time()}
    args.output.write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
