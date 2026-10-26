#!/usr/bin/env python3
"""One real-asset skill feasibility check using the frozen physical worker."""
import argparse
import asyncio
import json
from pathlib import Path

from real_breakfast_worker import World


async def run(args):
    world = World({"output": str(args.output / "physics"), "seed": args.seed,
                   "max_steps": args.limit, "policy_port": args.port,
                   "backend": "pi05"})
    try:
        before = world.snapshot()
        execution = await world.execute({"object_id": args.object_id,
                                         "destination": args.destination,
                                         "max_steps": args.limit})
        report = {"success": execution["success"],
                  "failure_domain": execution["failure_domain"],
                  "failure_reason": execution["failure_reason"],
                  "steps_used": execution["steps_used"],
                  "source": before["locations"][args.object_id],
                  "final": execution["after"]["locations"][args.object_id],
                  "final_position": execution["after"]["object_positions"][args.object_id]}
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        await world.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--object-id", required=True)
    p.add_argument("--destination", required=True)
    asyncio.run(run(p.parse_args()))
