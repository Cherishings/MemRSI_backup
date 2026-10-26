"""Link completed trials; never rerun or rewrite them during orchestration repair."""
import json,hashlib
from pathlib import Path
from feedback_protocol import schedule,plan,histories
from memory_policy import BASE
from physical_runner import same_process
from run_queue import ROOT

UNCHANGED_RUNTIME=(
 'agent_adapter.py','twenty_agent.py','memory_ops.py','memory_policy.py','memory_budget.py',
 'model_provider.py','runtime_config.py','token_accounting.py','feedback_protocol.py','feedback_workflow.py',
 'native_world.py','world_client.py','check_case.py','paired_sampling.py','serve_paired_policy.py',
 'retry_recovery.py','osc_handoff.py','action_catalog.py','execution_contract.py','configs/selected-budget.json')

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate_rows(rows,planned):
    index={r['trial_id']:r for r in planned};seen=set()
    for row in rows:
        tid=row['trial_id']
        if tid in seen or tid not in index:raise ValueError('resume_duplicate_or_unknown_trial')
        if any(row.get(k)!=v for k,v in index[tid].items()):raise ValueError('resume_trial_design_changed')
        if row['status'] not in ('success','decision_failure','execution_failure'):raise ValueError('resume_not_capability_terminal')
        seen.add(tid)
    return seen

def inspect_parent(parent):
    parent=Path(parent);manifest=read(parent/'manifest.json');progress=read(parent/'progress.json');rows=read(parent/'rows.json')
    if progress.get('active') or progress.get('status') not in ('failed','completed','no_accepted_improvement'):
        raise ValueError('resume_parent_not_stopped')
    records=[read(parent/'coordinator.json'),read(parent/'learning-process.json')]
    records.extend(read(p) for p in (parent/'gpu-workers').glob('policy-*.identity.json'))
    records.extend(r['worker'] for r in rows)
    if any(same_process(r) for r in records):raise ValueError('resume_parent_process_alive')
    if manifest['schedule']!=schedule() or manifest['protocols']!=json.loads(json.dumps({h:plan(h) for h in sorted(histories())})):
        raise ValueError('resume_protocol_changed')
    if read(parent/'policies/fixed.json')!=BASE:raise ValueError('resume_fixed_policy_changed')
    oldroot=Path(read(parent.parent/'launch.json')['code'])
    if any((ROOT/n).read_bytes()!=(oldroot/n).read_bytes() for n in UNCHANGED_RUNTIME):
        raise ValueError('resume_runtime_changed')
    validate_rows(rows,schedule())
    refs=[]
    for row in rows:
        path=Path(row['output'])/'result.json';r=read(path)
        if any(row.get(k)!=v for k,v in r.items() if k!='arm'):
            raise ValueError('resume_result_mismatch')
        # Runner arm 'fixed' maps to actor arm 'memrsi'.
        expected_arm='native' if row['arm']=='native' else 'memrsi'
        if r['arm']!=expected_arm:raise ValueError('resume_actor_arm_mismatch')
        refs.append({'trial_id':row['trial_id'],'source':str(path),'sha256':sha(path)})
    if len(rows)!=4:raise ValueError('resume_expected_four_pilots')
    return rows,{'parent':str(parent),'completed_trial_refs':refs,'same_runtime_files':list(UNCHANGED_RUNTIME),
                 'old_attempts_preserved':True,'no_new_test_feedback_to_optimizer':True}
