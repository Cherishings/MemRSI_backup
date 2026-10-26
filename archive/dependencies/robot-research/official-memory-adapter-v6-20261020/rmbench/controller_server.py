"""Local-only execution RPC; actor supplies RGB, joint state, and instruction only."""
import argparse
import base64
import http.server
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=19242)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import setproctitle
    setproctitle.setproctitle('robot')
    import numpy as np
    from frozen_executor import FrozenRMBenchExecutor
    args.output.mkdir(parents=True, exist_ok=True)
    controller = FrozenRMBenchExecutor()
    setproctitle.setproctitle('robot')

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8_000_000:
                    raise ValueError('invalid payload size')
                payload = json.loads(self.rfile.read(size))
                if self.path == '/reset':
                    if set(payload) != {'episode_seed'}:
                        raise ValueError('reset contract mismatch')
                    controller.reset(int(payload['episode_seed']))
                    reply = {'status': 'reset', 'controller': controller.identity}
                elif self.path == '/predict':
                    if set(payload) != {'rgb_base64', 'rgb_shape', 'joint_state', 'instruction', 'new_subtask'}:
                        raise ValueError('actor observation contract mismatch')
                    shape = tuple(payload['rgb_shape'])
                    if len(shape) != 3 or shape[-1] != 3 or any(not isinstance(x, int) or not 1 <= x <= 2048 for x in shape):
                        raise ValueError('invalid RGB shape')
                    raw = base64.b64decode(payload['rgb_base64'], validate=True)
                    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(shape)
                    reply = controller.predict(rgb, payload['joint_state'], payload['instruction'], new_subtask=payload['new_subtask'])
                    setproctitle.setproctitle('robot')
                    reply['actions'] = reply['actions'].tolist()
                elif self.path == '/observe_step':
                    if set(payload) != {'rgb_base64', 'rgb_shape', 'joint_state'}:
                        raise ValueError('step observation contract mismatch')
                    shape = tuple(payload['rgb_shape'])
                    if len(shape) != 3 or shape[-1] != 3 or any(type(x) is not int or not 1 <= x <= 2048 for x in shape):
                        raise ValueError('invalid RGB shape')
                    rgb = np.frombuffer(base64.b64decode(payload['rgb_base64'], validate=True), dtype=np.uint8).reshape(shape)
                    reply = controller.observe_step(rgb, payload['joint_state'])
                else:
                    self.send_error(404)
                    return
                content = json.dumps(reply).encode()
                self.send_response(200)
            except Exception as error:
                content = json.dumps({'error_type': type(error).__name__, 'error': str(error)[:500]}).encode()
                self.send_response(422)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = http.server.HTTPServer(('127.0.0.1', args.port), Handler)
    identity = {'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
                'port': args.port, 'ready': time.time(), 'controller': controller.identity}
    (args.output / 'controller-ready.json').write_text(json.dumps(identity, indent=2))
    server.serve_forever()


if __name__ == '__main__':
    main()
