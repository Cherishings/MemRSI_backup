"""Conditional cross-platform paired evaluation; no GPU while waiting for LIBERO."""
import argparse
import asyncio
import collections
import hashlib
import json
import subprocess
import time
from pathlib import Path
import run as engine
from scale_protocol import cases, BUDGET, libero_gate

SOURCE = Path('/data/stormlab/xi/paos/qwen-deploy/latest-memrsi-bounded-v2_2.json')


def read(p, default=None):
    return engine.read(p) if p.exists() else default


def summarize(rows, plans):
    summary = {}
    for arm in ('native','memrsi'):
        rr=[r for r in rows if r['arm']==arm]
        groups={}
        for p in plans:
            groups.setdefault(p['paired_history_id'],[]).append(p['id'])
        succeeded={r['case'] for r in rr if r['status']=='success'}
        summary[arm]=dict(planned_trials=48,terminal=len(rr),success=len(succeeded),
            counts=dict(collections.Counter(r['status'] for r in rr)),
            planned_checkpoints=sum(p['planned_checkpoints'] for p in plans),
            reached=sum(r['answered'] for r in rr),correct=sum(r['correct'] for r in rr),
            paired_history_passes=sum(set(ids)<=succeeded for ids in groups.values()),
            planned_history_pairs=len(groups),
            by_kind={kind:dict(terminal=sum(r['kind']==kind for r in rr),
                              success=sum(r['kind']==kind and r['status']=='success' for r in rr))
                     for kind in ('resume','delayed','revision','cancellation')})
    return summary


def main(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True);plans=cases(a.platform)
    source=read(SOURCE)
    if not source:raise RuntimeError('missing_libero_source')
    frozen_source=read(out/'source-pointer.json')
    if frozen_source and frozen_source!=source:raise RuntimeError('source_pointer_changed')
    engine.dump(out/'source-pointer.json',source)
    root=Path(source['result'])
    manifest=dict(version='memory-scale-v2.2',platform=a.platform,gpu=a.gpu,plans=plans,
        per_arm_trials=48,instruction_conditions=24,repeats_per_condition=2,methods=['native','memrsi'],
        budget=BUDGET,no_test_feedback_to_learning=True,
        scope='custom workflows, not official benchmark score; reused qualified layouts',
        executor='official_RoboTwin_expert_gripper' if a.platform=='twin' else 'official_open_loop_gripper_actions',
        launch_gate='LIBERO48 complete; adopted rule and validation; matched success >= fixed and > native')
    if read(out/'manifest.json') not in (None,manifest):raise RuntimeError('manifest_changed')
    engine.dump(out/'manifest.json',manifest)
    while True:
        gate=libero_gate(read(root/'report.json'),read(root/'learning/report.json'),read(root/'paired-summary.json'))
        engine.dump(out/'gate.json',gate)
        if gate['state']=='ready':break
        if gate['state']=='not_ready':
            engine.dump(out/'report.json',dict(status='not_launched_libero_gate',gate=gate,physical_trials=0));return
        engine.status(out,'waiting_libero_result_no_gpu_reserved')
        if engine.STOP.wait(30):return
    policy=read(root/'frozen-policy.json');freeze=read(root/'freeze.json')
    digest=hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()
    if digest!=freeze['sha256']:raise RuntimeError('frozen_policy_mismatch')
    engine.dump(out/'rsi-source.json',dict(source=str(root),sha256=digest,freeze=freeze))
    rows=[]
    for i,plan in enumerate(plans):
        for arm in (('native','memrsi') if i%2==0 else ('memrsi','native')):
            case=out/arm/plan['id'];saved=read(case/'result.json')
            if saved:rows.append(saved);continue
            attempts=[]
            for attempt in range(1,4):
                d=case/f'attempt-{attempt:02d}';r=read(d/'result.json')
                if r is None and d.exists():
                    r=dict(status='technical_failure',error_code='interrupted_trial',arm=arm,case=plan['id'],
                           planned=plan['planned_checkpoints'],answered=0,correct=0,
                           partial_evidence_preserved=True)
                    # Never overwrite an interrupted attempt or invent its partial score.
                    engine.dump(d/'result.json',r)
                if r is None:
                    if engine.STOP.is_set():return
                    engine.gateway_contract(engine.STOP,lambda:engine.status(out,'waiting_gateway'))
                    used=lambda:int(subprocess.check_output(['nvidia-smi','-i',str(a.gpu),
                        '--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
                    engine.status(out,'waiting_gpu',arm=arm,case=plan['id'],attempt=attempt)
                    with engine.acquire(engine.LEASES/engine.lock_name(a.gpu),True,used):
                        engine.status(out,'trial',arm=arm,case=plan['id'],attempt=attempt)
                        r=asyncio.run(engine.trial(plan,arm,policy if arm=='memrsi' else None,a.gpu,d))
                attempts.append(dict(path=str(d),status=r['status'],error_code=r.get('error_code')))
                # Known execution/decision/protocol/capacity failures are final, not rerolled.
                if r.get('error_code')=='unclassified_exception':
                    engine.dump(out/'report.json',dict(status='blocked_code_or_environment',case=plan['id'],arm=arm));return
                if r['status']!='technical_failure':break
            final=dict(r,kind=plan['kind'],condition=plan['condition'],repeat=plan['repeat'],
                       paired_history_id=plan['paired_history_id'],attempts=attempts)
            engine.dump(case/'result.json',final);rows.append(final);engine.dump(out/'rows.json',rows)
    engine.dump(out/'report.json',dict(status='completed',terminal=len(rows),summary=summarize(rows,plans),
        scope=manifest['scope'],old_pilot_not_pooled=True,policy_updated_during_evaluation=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--platform',choices=['twin','casa'],required=True)
    p.add_argument('--gpu',type=int,choices=range(7),required=True);p.add_argument('--output',required=True)
    main(p.parse_args())
