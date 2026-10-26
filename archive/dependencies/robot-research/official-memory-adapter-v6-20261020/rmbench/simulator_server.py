"""Native RMBench qpos execution service with a restricted observation surface."""
import argparse
import base64
import http.server
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=19243)
    parser.add_argument('--task', default='cover_blocks', choices=['cover_blocks'])
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    import numpy as np
    import imageio.v2 as imageio
    import setproctitle
    setproctitle.setproctitle('robot')
    from adapters import RMBench
    args.output.mkdir(parents=True, exist_ok=True)
    world = RMBench(args.task, args.seed, args.output)
    setproctitle.setproctitle('robot')
    video = imageio.get_writer(args.output / 'episode.mp4', fps=20)
    closed = False

    def observation():
        obs = world.observe()
        names = sorted(obs['images'], key=lambda key: ('head' not in key, key))[:3]
        cameras = []
        for name in names:
            rgb = np.asarray(obs['images'][name], dtype=np.uint8)[:, :, :3].copy()
            cameras.append({'name': name, 'shape': list(rgb.shape), 'rgb_base64': base64.b64encode(rgb.tobytes()).decode()})
        joints = np.asarray(obs['joint_action']['vector'], dtype=np.float32)
        if joints.shape != (14,) or not np.isfinite(joints).all():
            raise ValueError('native embodiment state must have 14 finite dimensions')
        return {'instruction': world.instruction, 'cameras': cameras,
                'proprio': {'joint_action': joints.tolist()},
                'steps': world.steps, 'horizon': world.horizon}

    initial = observation()
    imageio.imwrite(args.output / 'initial-scene.png', world.frames()[0])
    (args.output / 'public-contract.json').write_text(json.dumps({
        'action_dim': world.action_dim, 'instruction': world.instruction,
        'camera_names': [x['name'] for x in initial['cameras']],
        'proprio_keys': list(initial['proprio']), 'privileged_fields_exposed': False}, indent=2))

    def close():
        nonlocal closed
        if closed:
            return
        closed = True
        video.close()
        result = {'status': 'smoke_complete' if args.smoke else ('success' if world.success else 'task_failure'),
                  'task': args.task, 'seed': args.seed, 'steps': world.steps,
                  'official_check_success': bool(world.success),
                  'scope': 'infrastructure smoke, not a score' if args.smoke else 'paired PAOS/MemRSI with shared frozen learned execution controller',
                  'finished': time.time()}
        (args.output / 'result.json').write_text(json.dumps(result, indent=2))
        world.close()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                if closed:
                    raise ValueError('episode already closed')
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 200000:
                    raise ValueError('invalid payload size')
                payload = json.loads(self.rfile.read(size))
                if self.path == '/observe' and payload == {}:
                    reply = {'public': observation()}
                elif self.path == '/step' and set(payload) == {'actions'}:
                    actions = np.asarray(payload['actions'], dtype=np.float32)
                    if actions.ndim != 2 or actions.shape[1] != 14 or not 1 <= len(actions) <= 8 or not np.isfinite(actions).all():
                        raise ValueError('expected 1..8 finite native 14-D actions')
                    done = False
                    before_steps = world.steps
                    for action in actions:
                        _, _, done = world.step(action)
                        video.append_data(world.frames()[0])
                        with (args.output / 'actions.jsonl').open('a') as handle:
                            handle.write(json.dumps({'step': world.steps, 'qpos': action.tolist()}) + '\n')
                        if done:
                            break
                    reply = {'public': observation(), 'evaluator': {'done': done, 'success': bool(world.success)},
                             'receipt': f'Executed {world.steps - before_steps} commanded joint steps in the simulator. Current camera observation follows.'}
                elif self.path == '/close' and payload == {}:
                    close()
                    reply = {'closed': True}
                else:
                    raise ValueError('unknown request contract')
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
    (args.output / 'simulator-ready.json').write_text(json.dumps({
        'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
        'port': args.port, 'task': args.task, 'seed': args.seed, 'ready': time.time()}, indent=2))
    try:
        while not closed:
            server.handle_request()
    finally:
        close()


if __name__ == '__main__':
    main()
