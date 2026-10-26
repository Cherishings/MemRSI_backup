"""Rebuild cycle0 selector inputs from audited recoveries; no model requests."""
import hashlib
import json
import sys
import time
from pathlib import Path

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def cumulative_calls(paths):
    total=0
    for path in paths:
        total+=read(path/'calls.json')['calls']
    return total

def main():
    R=Path('/data/stormlab/xi/robot')
    code=R/'paper-evolution-20261018r1'
    sys.path[:0]=[str(code),str(code/'frozen_runtime')]
    from trajectory_evolution import select
    from protocol import verify_runtime
    verify_runtime(code)
    root=R/'runs/paper-evolution-20261018'
    repair=R/'runs/paper-completion-20261020/archive-transport-repair'
    audit=read(repair/'audit.json')
    summary=[]
    for run in read(root/'authorization.json')['runs']:
        old=root/'studies'/run/'cycle-0'
        output=repair/'reconciliation'/run
        output.mkdir(parents=True,exist_ok=True)
        original=read(old/'paired-rows.json')
        rows=[];provenance=[];unresolved=[]
        confirmed={x['relative']:x for x in audit['confirmed_transport']
                   if x['run_id']==run and x['relative'].startswith('cycle-0/')}
        for row in original:
            relative=f"cycle-0/{row['policy']}-replays/{row['case']}-r{row['repeat']}-{row['policy']}"
            src=root/'studies'/run/relative
            item=confirmed.get(relative)
            chosen=src/'result.json'
            r=dict(row)
            if item:
                if sha(chosen)!=item['original_result_sha256']:raise RuntimeError('source_changed')
                dest=repair/'recovery'/run/relative
                if not (dest/'result.json').exists():
                    unresolved.append(relative)
                    r['status']='technical_failure'
                else:
                    recovered=read(dest/'result.json')
                    ra=read(dest/'recovery-audit.json')
                    if ra['original']!=item:raise RuntimeError('recovery_audit_changed')
                    if recovered['status'] in ('technical_failure','unclassified_failure','learning_budget_exhausted'):
                        unresolved.append(relative)
                    last=dest/f"attempt-{recovered['attempts']:02d}"
                    if sha(last/'policy.json')!=item['policy_sha256']:raise RuntimeError('recovery_policy_changed')
                    attempts=list(src.glob('attempt-*'))+list(dest.glob('attempt-*'))
                    if len(attempts)>3:raise RuntimeError('attempt_limit')
                    total=cumulative_calls(attempts)
                    if total<row.get('all_attempt_calls',0):raise RuntimeError('cost_reset')
                    r=dict(recovered,case=row['case'],repeat=row['repeat'],policy=row['policy'],
                           all_attempt_calls=total)
                    if r['source']!=row['source'] or r['planned']!=row['planned']:
                        raise RuntimeError('source_or_denominator_changed')
                    chosen=dest/'result.json'
            rows.append(r)
            provenance.append(dict(case=row['case'],repeat=row['repeat'],policy=row['policy'],
                                   source=str(chosen),sha256=sha(chosen),
                                   audited_recovery=bool(item),all_attempt_calls=r.get('all_attempt_calls',0)))
        # Unresolved archive labels without same-call evidence stay unchanged;
        # they are not retrospectively recategorized by this operation.
        effect=select(rows,8)
        oldselection=read(old/'selection.json')
        report=dict(run_id=run,status='blocked_unresolved_technical' if unresolved else 'reconciled',
                    effect=effect,unresolved=unresolved,old_selection=oldselection['effect'],
                    parent_policy_file_sha256=sha(old/'parent-policy.json'),
                    candidate_policy_file_sha256=sha(old/'candidate-policy.json'),
                    original_selector_unchanged=True,all_prior_attempt_costs_retained=True,
                    no_new_model_calls=True,
                    cycle1_action='repair_original_parent_only_then_regenerate_diagnosis_and_proposal'
                      if not unresolved and not effect['accepted'] else 'requires_dependency_audit',
                    old_cycle1_proposals_invalidated=True,time=time.time())
        for name,data in [('paired-rows.json',rows),('provenance.json',provenance),('report.json',report)]:
            (output/name).write_text(json.dumps(data,indent=2))
        summary.append(report)
    (repair/'reconciliation-summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps([dict(run=x['run_id'],status=x['status'],effect=x['effect'],
                          unresolved=x['unresolved']) for x in summary]))

if __name__=='__main__':main()
