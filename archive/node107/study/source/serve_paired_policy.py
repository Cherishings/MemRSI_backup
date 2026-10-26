"""Isolated wrapper: no changes to openpi or checkpoint weights."""
import argparse
from openpi.policies import policy_config
from openpi.training import config
from openpi.serving.websocket_policy_server import WebsocketPolicyServer
from paired_sampling import PairedPolicy

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--port', type=int, required=True); p.add_argument('--checkpoint', required=True)
    args = p.parse_args()
    c = config.get_config('pi05_libero')
    policy = policy_config.create_trained_policy(c, args.checkpoint)
    wrapper = PairedPolicy(policy, (c.model.action_horizon, c.model.action_dim))
    WebsocketPolicyServer(wrapper, host='127.0.0.1', port=args.port,
        metadata=dict(policy.metadata, paired_sampling=True, noise_shape=list(wrapper.shape))).serve_forever()
