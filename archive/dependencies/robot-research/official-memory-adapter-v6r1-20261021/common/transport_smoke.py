"""Two-arm synthetic-camera transport check; no robot/benchmark score."""
import asyncio
import argparse
import json
from pathlib import Path
import numpy as np
from visual_actor import VisualAgent


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    policy = Path('/data/stormlab/xi/paos/results/memrsi-bounded-v2_2-20261015T175555Z/experiment/frozen-policy.json')
    camera = np.zeros((64, 64, 3), dtype=np.uint8)
    camera[:, :, 0] = 255
    rows = []
    for arm in ('native', 'memrsi'):
        actor = VisualAgent(arm, output / arm, policy if arm == 'memrsi' else None,
                            {'persistent_tokens': 1024, 'active_input_tokens': 12288})
        try:
            choice = await actor.choose(
                'Camera transport test only, no robot is connected. Submit execute '
                'with instruction equal to the single basic color visible in the image. '
                'This tests image delivery; do not move a robot.', [camera], {})
            session = actor.loop.sessions.get_or_create(actor.session_key)
            saved = json.dumps(session.messages)
            row = dict(arm=arm, choice=choice, calls=actor.provider.calls,
                       image_payload_not_kept_in_native_history='data:image/' not in saved,
                       scope='synthetic camera transport check; not a benchmark trial')
            rows.append(row)
        except Exception as e:
            rows.append(dict(arm=arm, error_type=type(e).__name__, scope='transport check'))
        finally:
            await actor.close()
    (output / 'result.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--output', required=True, type=Path)
    asyncio.run(run(p.parse_args().output))
