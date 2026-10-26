"""Real-model plumbing smoke. No physical or method-effectiveness claim."""
import argparse
import asyncio
from pathlib import Path
from agent_adapter import Agent
from replay import dump

async def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    records=[]
    for arm in ('native','memrsi'):
        a=Agent(arm,out/arm,memory_policy=Path(__file__).parent/'configs/base-policy.json' if arm=='memrsi' else None)
        try:
            await a.observe_only('Prepare service table one, then service table two. Before table two, attend to a temporary work order.',{})
            await a.replay_observe('Continue.',{'skill':'serve_table_one','reason':'Begin the requested service.'})
            await a.observe_only('Execution feedback: service table one is complete. Temporary kitchen work order completed.',{})
            await a.rollover()
            choice=await a.turn('Continue.',{},decision=True)
            records.append({'arm':arm,'choice':choice,'archive_success':a.rollovers[-1]['success'],
                            'model_calls':a.provider.calls,'scope':'model/archive plumbing only; no actual gripper execution'})
        finally:await a.close()
    dump(out/'result.json',records)
    print([{'arm':r['arm'],'choice':r['choice']['skill'],'archive_success':r['archive_success'],'calls':r['model_calls']} for r in records],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    asyncio.run(run(p.parse_args().output))
