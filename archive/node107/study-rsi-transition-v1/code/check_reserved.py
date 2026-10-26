"""One pre-registered unused-condition check; no proposal or rule editing."""
import asyncio,json,os,pathlib,sys,time
from types import SimpleNamespace
import learn
B=pathlib.Path('/data/songziying/paos-libero-20261023')
R=B/'study-rsi-joint-v1';O=R/'learning';OLD=B/'study-rsi-v4-learning-compact/learning'
async def main():
    registration=learn.read(R/'reserved-check-registration.json')
    combinations={k:learn.read(O/'policies'/f'{k}.json') for k in learn.ARMS}
    assert {k:learn.digest(v) for k,v in combinations.items()}==registration['candidate_hashes']
    a=SimpleNamespace(source=str(R/'source'),core=str(R/'paos-core'),budget=str(R/'budget.json'))
    learn.install_runtime(a.source,a.core)
    try:
        rows=await learn.run_stage(a,O,'reserved-condition-check',registration['sources'],combinations,O/'learning-call-ledger.json')
        scores={k:learn.score_pair(rows,k,2,validation=True) for k in combinations if k!='parent'}
        training=learn.read(O/'training-selection.json')
        passed=training['joint']['passed'] and scores['joint']['passed']
        learn.write(O/'reserved-condition-report.json',{'status':'reserved_condition_complete','joint_gate_passed':passed,
          'scores':scores,'primary_candidate':'joint','candidate_hashes':registration['candidate_hashes'],
          'scope':'One previously unused condition, same history family as prior validation; not independent-history or final physical evaluation',
          'physical_evaluation_runs':0,'test_feedback_used':False,'ledger':learn.read(O/'learning-call-ledger.json')})
    except BaseException as e:
        learn.write(O/'reserved-condition-blocked.json',{'type':type(e).__name__,'error':str(e),'automatic_resampling':False});raise
if __name__=='__main__':asyncio.run(main())
