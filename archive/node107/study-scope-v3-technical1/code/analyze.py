"""Registered paired analysis; no test feedback is sent to the learner."""
import itertools, json, random
from pathlib import Path
from run_case import write

def paired(rows, a, b, seed=20261023):
    left_rows=[x for x in rows if x['arm']==a];right_rows=[x for x in rows if x['arm']==b]
    left={x['condition_id']:x for x in left_rows}
    right={x['condition_id']:x for x in right_rows}
    if len(left)!=len(left_rows) or len(right)!=len(right_rows):raise ValueError('duplicate_paired_condition')
    if set(left)!=set(right) or len(left)!=48:raise ValueError('incomplete_paired_conditions')
    groups={};wins=losses=0
    for key in sorted(left):
        l,r=left[key],right[key]
        x=int(l['result']['status']=='success');y=int(r['result']['status']=='success')
        wins+=int(x>y);losses+=int(x<y)
        groups.setdefault(l['history'],[]).append(x-y)
    if len(groups)!=12 or any(len(values)!=4 for values in groups.values()):
        raise ValueError('registered_history_block_structure_changed')
    block=[sum(v)/len(v) for k,v in sorted(groups.items())]
    delta=sum(block)/len(block);rng=random.Random(seed)
    samples=sorted(sum(rng.choices(block,k=len(block)))/len(block) for _ in range(10000))
    null=[sum(s*x for s,x in zip(signs,block))/len(block) for signs in itertools.product((-1,1),repeat=len(block))]
    p=sum(x>=delta-1e-12 for x in null)/len(null)
    loo=[sum(block[:i]+block[i+1:])/(len(block)-1) for i in range(len(block))]
    return dict(left=a,right=b,paired_n=48,wins=wins,losses=losses,success_rate_difference=delta,
        history_block_differences=dict(zip(sorted(groups),block)),history_blocks=len(block),
        cluster_bootstrap_95_interval=[samples[249],samples[9749]],bootstrap_seed=seed,
        sign_flip_one_sided_p_under_symmetry=p,leave_one_history_out_min=min(loo),
        all_leave_one_history_out_positive=all(x>0 for x in loo),
        inferential_limit='Mission-order blocks share physical tasks. Sign-flip assumes symmetric independent block effects; it is sensitivity evidence, not a randomized task-family generalization test.')

def main(root):
    root=Path(root);m=json.loads((root/'registration.json').read_text());f=json.loads((root/'final-registration.json').read_text())
    rows=json.loads((root/'final/completed-results.json').read_text());aliases=f['aliases']
    registered={c['condition_id']:c for c in m['test_conditions']}
    if len(rows)!=48*len(f['distinct_arms']):raise ValueError('incomplete_final_result_count')
    identities=set()
    for row in rows:
        identity=(row['condition_id'],row['arm'])
        if identity in identities:raise ValueError('duplicate_final_result')
        identities.add(identity)
        expected=registered.get(row['condition_id'])
        if row['arm'] not in f['distinct_arms'] or expected is None or any(row[k]!=expected[k] for k in ('history','init','variant')):
            raise ValueError('unregistered_final_result')
        if row['result'].get('registered_arm')!=row['arm'] or row['result'].get('condition_id')!=row['condition_id']:
            raise ValueError('result_identity_mismatch')
    def actual(a):return aliases.get(a,a)
    summary={}
    for arm in m['final_arms']:
        arm_rows=[x for x in rows if x['arm']==actual(arm)]
        rr=[x['result'] for x in arm_rows];fail={};statuses={};calls=[]
        if len(rr)!=48:raise ValueError('incomplete_arm')
        for row in arm_rows:
            r=row['result'];statuses[r['status']]=statuses.get(r['status'],0)+1
            if r['status']!='success':
                failure=r['registered_failure_class'];fail[failure]=fail.get(failure,0)+1
            count=r.get('logical_calls')
            if type(count) is not int:
                ledger=Path(row['output'])/'calls.json'
                count=json.loads(ledger.read_text()).get('calls') if ledger.exists() else None
            calls.append(count if type(count) is int and count>=0 else None)
        summary[arm]=dict(executed_as=actual(arm),successes=sum(r['status']=='success' for r in rr),planned=48,
            failure_classes=fail,status_counts=statuses,
            logical_calls_known=sum(x for x in calls if x is not None),logical_call_records_missing=sum(x is None for x in calls),
            planned_checkpoints=sum(r.get('planned_checkpoints',0) for r in rr),
            reached_checkpoints=sum(r.get('reached_checkpoints',0) for r in rr),
            answered_checkpoints=sum(r.get('answered_checkpoints',0) for r in rr),
            correct_checkpoints=sum(r.get('correct_checkpoints',0) for r in rr),
            model_input_tokens=sum(r.get('model_input_tokens',0) for r in rr),
            model_output_tokens=sum(r.get('model_output_tokens',0) for r in rr),
            cost_complete=all(r.get('model_cost_complete',False) for r in rr),
            elapsed_seconds=sum(r.get('elapsed_seconds',0) for r in rr))
    comparisons=[]
    for a,b in m['primary_comparisons']:
        value=paired(rows,actual(a),actual(b));value.update(requested_left=a,requested_right=b,
            identical_policy_alias=actual(a)==actual(b));comparisons.append(value)
    order=sorted(range(len(comparisons)),key=lambda i:comparisons[i]['sign_flip_one_sided_p_under_symmetry'])
    running=0
    for rank,i in enumerate(order):
        running=max(running,min(1,comparisons[i]['sign_flip_one_sided_p_under_symmetry']*(len(order)-rank)))
        comparisons[i]['holm_adjusted_sensitivity_p']=running
    learning_comparisons=[]
    for a,b in m.get('secondary_learning_comparisons',[]):
        operator={'rsi_g_only':'guidance','rsi_u_only':'update'}[a]
        value=paired(rows,actual(a),actual(b))
        value.update(requested_left=a,requested_right=b,operator=operator,
            operator_changed=operator in f['changed_operators'],
            identical_policy_alias=actual(a)==actual(b),
            inferential_role='Registered secondary learning contrast; unadjusted sensitivity p, not an additional confirmatory primary claim.')
        learning_comparisons.append(value)
    report=dict(scope=m['scope'],summary=summary,primary_comparisons=comparisons,
        secondary_learning_comparisons=learning_comparisons,
        learned_operators=f['changed_operators'],aliases=aliases,
        rsi_algorithm_report=str(root/'learning/report.json'),
        no_automatic_positive_claim=True,
        conclusion_rule='Report effects and uncertainty, including negative results. No claim of independent G/U learning when that operator was unchanged. Manual parent improvements are not RSI.')
    write(root/'analysis.json',report)
    return report
if __name__=='__main__':
    import sys
    main(sys.argv[1])
