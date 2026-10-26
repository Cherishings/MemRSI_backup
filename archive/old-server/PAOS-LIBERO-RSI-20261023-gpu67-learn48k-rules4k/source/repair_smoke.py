"""Bounded real-model replay of three known failures, not new physical results."""
import asyncio,argparse,json
from pathlib import Path
from replay import evaluate,dump
from memory_policy import BASE
async def main(out,source):
    out=Path(out);out.mkdir(exist_ok=False,parents=True);policy=out/'base-policy.json';dump(policy,BASE)
    names=['init0-jobs12-resume-one_first','init0-jobs12-delay-one_first','init0-jobs12-cancel-two_first']
    results=[]
    for name in names:
        row=await evaluate(Path(source)/'discovery'/name,out/name,policy)
        results.append({k:row.get(k) for k in ['source','status','observed','correct','passed','error_code','model_calls','decisions']})
        dump(out/'progress.json',dict(terminal=len(results),planned=len(names),results=results))
    dump(out/'report.json',{'all_saved_checkpoints_passed':all(r['passed'] for r in results),'results':results,'scope':'development regressions; human interface repair, not learned RSI benefit'})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--source',required=True);a=p.parse_args();asyncio.run(main(a.output,a.source))
