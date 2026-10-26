"""Real protocol smoke, no heldout task/answer and no physical policy changes."""
import asyncio,argparse,json
from pathlib import Path
from replay import dump
from twenty_agent import TwentyAgent
from stream_design import SEED_PROCEDURES,compile_procedures
from memory_policy import digest
async def main(path):
 p=Path(path);p.mkdir(parents=True,exist_ok=False);policy=compile_procedures(SEED_PROCEDURES);dump(p/'policy.json',policy)
 a=TwentyAgent('memrsi',p/'actor',p/'policy.json',Path(__file__).parent/'configs/selected-budget.json')
 try:
  await a.observe_only('Transport smoke only: remember that the notebook label is violet. No physical work is requested.')
  for i in range(3):
   result=await a.ops.guide([], 'Read relevant notebook evidence; this is not an action decision.')
   if not isinstance(result,str):raise RuntimeError('smoke_guidance')
  await a.rollover()
  await a.ops.guide([], 'Read relevant remembered notebook evidence. No physical work is requested.')
  dump(p/'report.json',{'status':'passed','guidance_requests':4,'native_archive':True,
    'policy_hash':digest(policy),'model_calls':a.provider.calls,'physical_trials':0,'heldout_access':False})
 finally:await a.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();asyncio.run(main(a.output))
