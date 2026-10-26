"""Small real-provider protocol check, no test task and no physical trial."""
import argparse
import asyncio
from pathlib import Path
from replay import dump
from twenty_agent import TwentyAgent
from stream_design import SEED_PROCEDURES,compile_procedures
from unified_pipeline import gateway_contract

async def run(path):
    out=Path(path);out.mkdir(parents=True,exist_ok=False)
    health=gateway_contract();p=out/'fixed.json';dump(p,compile_procedures(SEED_PROCEDURES))
    result=[]
    for arm in ('native','fixed','evolved'):
        a=TwentyAgent('native' if arm=='native' else 'memrsi',out/arm,
                      None if arm=='native' else p,Path(__file__).parent/'configs/selected-budget.json')
        try:
            if arm=='native' and a.ops is not None:raise RuntimeError('native_added_memory')
            await a.observe_only('Protocol check only. Remember that my notebook cover is violet. No robot action is requested.')
            await a.rollover()
            if a.ops is not None:await a.ops.guide([], 'Read relevant notebook evidence. No robot action is requested.')
            result.append({'arm':arm,'calls':a.provider.calls,'archive_ok':True,'guidance_ok':a.ops is not None})
        finally:await a.close()
    dump(out/'report.json',{'status':'passed','gateway':health,'arms':result,'heldout_access':False,
        'evolved_uses_seed_for_protocol_test_only':True,'physical_trials':0})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    asyncio.run(run(p.parse_args().output))
