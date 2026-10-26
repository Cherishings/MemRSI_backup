"""Loopback-only bridge for the separate actor, executor, and simulator runtimes."""
import base64
import json
import urllib.request


def post(port, method, payload, timeout=180):
    request = urllib.request.Request(f'http://127.0.0.1:{int(port)}/{method}',
                                     data=json.dumps(payload, allow_nan=False).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def decode_cameras(public):
    import numpy as np
    return [np.frombuffer(base64.b64decode(row['rgb_base64'], validate=True), dtype=np.uint8).reshape(row['shape']).copy()
            for row in public['cameras']]


def predict(port, public, instruction, new_subtask=False):
    head = public['cameras'][0]
    return post(port, 'predict', {'rgb_base64': head['rgb_base64'], 'rgb_shape': head['shape'],
                                'joint_state': public['proprio']['joint_action'], 'instruction': instruction,
                                'new_subtask': new_subtask})


def observe_step(port, public):
    head = public["cameras"][0]
    return post(port, "observe_step", {"rgb_base64": head["rgb_base64"], "rgb_shape": head["shape"], "joint_state": public["proprio"]["joint_action"]})
