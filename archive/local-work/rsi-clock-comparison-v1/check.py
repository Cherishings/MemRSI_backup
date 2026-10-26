"""Fixed three-policy development comparison, no optimizer or critic calls."""
import asyncio,json,sys
from pathlib import Path
import learn
async def main():
 r=Path(sys.argv[1]);reg=learn.read(r/'comparison-registration.json')
 class Args:pass
 a=Args();a.root=str(r);a.source=str(r/'source');a.core=str(r/'paos-core');a.budget=str(r/'budget.json')
 learn.install_runtime(a.source,a.core)
 out=r/'learning';ledger=out/'learning-call-ledger.json'
 policies={name:learn.read(out/'policies'/(name+'.json')) for name in reg['arms']}
 for n,p in policies.items():assert learn.digest(p)==reg['policy_hashes'][n]
 try:
  rows=await learn.run_stage(a,out,'training',reg['sources'],policies,ledger)
  scores={arm:learn.score_pair(rows,arm,8) for arm in reg['arms'] if arm!='parent'}
  passed=[n for n in scores if scores[n]['passed']]
  # Training-only selection, deterministic tie-break registered before dispatch.
  ranked=sorted(passed,key=lambda n:(-scores[n]['completed'][n],-scores[n]['totals'][n]['correct'],scores[n]['logical_calls'][n],n))
  learn.write(out/'report.json',{'status':'fixed_policy_comparison_complete','scores':scores,'selected_for_pilot':ranked[0] if ranked else None,'ledger':learn.read(ledger),'physical_success_claimed':False,'all_failures_retained':True,'no_optimizer_calls':True})
 except BaseException as e:
  learn.write(out/'blocked.json',{'error':str(e),'automatic_retry':False});raise
if __name__=='__main__':asyncio.run(main())
