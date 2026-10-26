"""Finite visual G/U adaptation, one reserved gate, then 48 paired tests.

Each benchmark is an explicit adaptation domain. Rules are frozen in every
episode. No formal test trace enters proposals. No automatic capability reruns.
"""
import argparse,asyncio,fcntl,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'common' if (HERE/'common').exists() else HERE/'new_common'))
from adaptation_protocol import (AdaptationProtocol,SPLITS,ROW_FIELDS,VALID_STATUSES,
                                 UNRESOLVED_STATUSES)
from source_compatibility import execution_source_matches
from visual_rule_proposal import policy_sha256
from learn_visual import (export_manifest,export_previous_development_feedback,
                          propose,write,immutable_json,ProposalPaused)
import run_trial

def read(p):return json.loads(Path(p).read_text())
class StagePaused(RuntimeError):pass

class LedgerBudget:
    """Read the real shared cumulative ledger; never initialize/reset a copy."""
    def __init__(self,path):self.path=Path(path)
    def snapshot(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_SH)
            d=read(self.path) if self.path.exists() else {'inherited_used':8986,'used':8986,'authorized_limit':9745}
            if d.get('inherited_used')!=8986 or type(d.get('used')) is not int or d['used']<8986:
                raise ValueError('learning_ledger_inheritance_mismatch')
            limit=d.get('authorized_limit')
            if type(limit) is not int or limit<9745 or d['used']>limit:
                raise ValueError('learning_ledger_limit_mismatch')
            if limit!=9745:
                approval=d.get('additional_authorization')
                if (not isinstance(approval,dict) or not approval.get('user_message')
                        or approval.get('total_limit')!=limit):
                    raise ValueError('learning_budget_authorization_missing')
        return {'calls':d['used'],'limit':d['authorized_limit'],
                'remaining':max(0,d['authorized_limit']-d['used']),
                'baseline':8986,'budget_reset':False,'source':str(self.path.resolve())}
    @property
    def remaining(self):return self.snapshot()['remaining']

def checked_cached_row(a,phase,method,ph,seed,folder):
    row=read(folder/'scored-record.json');meta=read(folder/'started.json')
    if not execution_source_matches(meta.get('source_hashes'),run_trial.source_hashes()):raise StagePaused('frozen_source_changed')
    if set(row)!=ROW_FIELDS:raise StagePaused('cached_result_schema_mismatch')
    wanted=dict(benchmark=a.benchmark,seed=seed,split=phase,policy_sha256=ph)
    if any(row.get(k)!=v or meta.get(k)!=v for k,v in wanted.items()):
        raise StagePaused('cached_result_identity_mismatch')
    if type(row['seed']) is not int or type(meta['seed']) is not int:
        raise StagePaused('cached_result_identity_mismatch')
    if row['method']!=meta.get('method') or row['method'] not in ('native','pre','post'):
        raise StagePaused('cached_result_method_mismatch')
    if (method=='native')!=(row['method']=='native'):
        raise StagePaused('cached_result_arm_mismatch')
    if row['status'] in UNRESOLVED_STATUSES:
        raise StagePaused('technical_case_requires_audit_not_automatic_retry')
    if row['status'] not in VALID_STATUSES:
        raise StagePaused('cached_result_unclassified_failure')
    if type(row['official_success']) is not bool or row['official_success']!=(row['status']=='success'):
        raise StagePaused('cached_result_official_score_inconsistent')
    return row

def one(a,phase,method,policy,seed):
    if phase not in SPLITS or type(seed) is not int or seed not in SPLITS[phase] or method not in ('native','pre','post'):
        raise StagePaused('unregistered_trial')
    ph=policy_sha256(read(policy)) if method!='native' else run_trial.native_policy_hash()
    folder=a.output/'trajectories'/phase/ph/str(seed)
    result=folder/'scored-record.json'
    if not result.exists():
        if any((folder/name).exists() for name in ('started.json','result.json','actor','controller','simulator')):
            raise StagePaused('interrupted_or_terminal_attempt_requires_audit_no_resampling')
        cmd=[sys.executable,str(HERE/'run_trial.py'),'--benchmark',a.benchmark,
             '--phase',phase,'--method',method,'--policy',str(policy),'--seed',str(seed),
             '--gpu',str(a.gpu),'--output',str(folder),'--ledger',str(a.ledger)]
        subprocess.run(cmd,check=False)
    if not result.exists():
        reason='learning_budget_wait_completed_trajectories_retained' if (folder/'waiting-learning-budget.json').exists() else 'incomplete_attempt_no_resampling'
        raise StagePaused(reason)
    row=checked_cached_row(a,phase,method,ph,seed,folder)
    # Identical policy/seed execution can be reused as a later round's parent.
    # Relabelling is limited to pre/post role, with original evidence retained.
    return dict(row,method=method),folder

def batch(a,phase,methods):
    rows=[];paths={m:{} for m in methods}
    for i,seed in enumerate(SPLITS[phase]):
        order=list(methods)
        if i%2:order.reverse()
        for method in order:
            row,path=one(a,phase,method,methods[method],seed)
            rows.append(row);paths[method][seed]=path
            write(a.output/'progress.json',dict(phase=phase,latest_seed=seed,latest_method=method,
                  accumulated_stage_results=len(rows),planned=len(SPLITS[phase])*len(methods)))
    return rows,paths

def save_protocol(a,p):write(a.output/'adaptation-state.json',p.manifest())

def release(a,protocol,initial,selected):
    qualification=read(a.qualification)
    if qualification.get('passed') is not True:raise StagePaused('engineering_qualification_not_passed')
    expected=run_trial.source_hashes()
    if qualification.get('source_hashes')!=expected:raise StagePaused('engineering_source_stamp_changed')
    # One shared file, safely merged when the other benchmark validates later.
    with (HERE/'release.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if protocol.phase!='ready_for_final_test':
            raise StagePaused('release_requires_completed_selection')
        validation=protocol.manifest()['validation_result']
        basis=protocol.selection_basis
        if basis=='validated_candidate':
            if (not protocol.validation_used or not validation or validation.get('passed') is not True
                    or protocol.current_policy==protocol.initial_policy or not protocol.evolution_supported):
                raise StagePaused('release_requires_passed_reserved_gate')
        elif basis=='unchanged_parent_fallback':
            if protocol.current_policy!=protocol.initial_policy or protocol.evolution_supported:
                raise StagePaused('fallback_policy_must_equal_initial')
        else:raise StagePaused('release_selection_basis_missing')
        selection=dict(basis=basis,evolution_supported=protocol.evolution_supported,
                       new_domain_rule_adopted=protocol.evolution_supported,
                       initial_policy_sha256=protocol.initial_policy,
                       evidence_scope='development_gain_and_reserved_nondecrease_not_significance',
                       reason=protocol.termination_reason)
        p=HERE/'release.json';v=read(p) if p.exists() else {'gate':'passed','source_hashes':expected,'policy_hashes':{},'validation':{},'selection':{}}
        if v.get('gate')!='passed' or v.get('source_hashes')!=expected:raise StagePaused('release_source_changed')
        hashes={'pre':policy_sha256(read(initial)),'post':policy_sha256(read(selected))}
        if hashes['pre']!=protocol.initial_policy or hashes['post']!=protocol.current_policy:
            raise StagePaused('validated_policy_file_changed')
        if a.benchmark in v['policy_hashes'] and (v['policy_hashes'][a.benchmark]!=hashes or v['validation'].get(a.benchmark)!=validation
                or v.get('selection',{}).get(a.benchmark)!=selection):
            raise StagePaused('existing_release_cannot_be_replaced')
        v['policy_hashes'][a.benchmark]=hashes
        v['validation'][a.benchmark]=validation
        v.setdefault('selection',{})[a.benchmark]=selection
        write(p,v)

async def run(a):
    a.output.mkdir(parents=True,exist_ok=True)
    with (a.output/'study.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        qualification=read(a.qualification)
        if qualification.get('passed') is not True or qualification.get('source_hashes')!=run_trial.source_hashes():
            raise StagePaused('engineering_qualification_missing_or_changed')
        policy=read(a.policy);ph=policy_sha256(policy)
        plan=dict(benchmark=a.benchmark,splits={k:list(v) for k,v in SPLITS.items()},
              maximum_learning_rounds=2,formal_methods=['native','post'],formal_pairs=48,
              learning_methods=['pre','post'],original_policy=ph,source_hashes=run_trial.source_hashes(),
              no_test_time_rule_learning=True,test_scope='selected_task_new_initial_states_not_full_official_suite',
              formal_claim_scope='whole_method_vs_native_not_isolated_evolution',
              evolution_claim_scope='development_and_reserved_validation_only',
              no_adoption_policy='unchanged_initial_rule_fallback_then_full_48_pairs',
              failed_reserve_policy='unchanged_initial_rule_fallback_then_full_48_pairs_no_retuning',
              unchanged_parent_requires_redundant_reserved_validation=False,
              inherited_calls=8986,default_total_limit=9745,learning_ledger=str(a.ledger.resolve()),
              worst_case_learning_calls_per_benchmark=28802,
              worst_case_is_estimate_not_required_prepayment=True,
              completed_development_trajectories_reused_when_budget_resumes=True)
        plan['second_proposal_feedback']='previous_local_edit_and_all_12_audited_development_pairs_only'
        immutable_json(a.output/'registered-plan.json',plan)
        initial=a.output/'frozen-initial-policy.json'
        immutable_json(initial,policy);selected=initial
        if (a.output/'study-complete.json').exists():return
        protocol=AdaptationProtocol(ph,benchmarks=(a.benchmark,),budget=LedgerBudget(a.ledger))
        previous_feedback=None
        try:
            for cycle in range(2):
                parent=selected;stage=a.output/f'round-{cycle+1}'
                parent_rows,paths=batch(a,'development',{'pre':parent})
                manifest=export_manifest(a.benchmark,read(parent),paths['pre'],stage/'evidence',
                                         expected_source_hashes=run_trial.source_hashes())
                candidate=await propose(parent,manifest,a.ledger,stage/'proposal',
                    previous_development_feedback=previous_feedback,
                    expected_source_hashes=run_trial.source_hashes(),proposal_round=cycle+1)
                if candidate.get('rejected'):
                    immutable_json(stage/'invalid-candidate.json',candidate)
                    if protocol.current_policy!=protocol.initial_policy:
                        # A malformed later proposal cannot erase an already
                        # adopted improvement. Freeze that rule and use the one
                        # reserved validation, without resampling the proposal.
                        protocol.freeze();save_protocol(a,protocol)
                        break
                    protocol.stop_without_improvement('candidate_rejected_no_resampling');save_protocol(a,protocol)
                    break
                candidate_path=stage/'proposal/policy.json'
                if candidate['candidate_policy_sha256'] in protocol.proposed_hashes or candidate['candidate_policy_sha256']==protocol.current_policy:
                    immutable_json(stage/'duplicate-candidate.json',dict(
                        candidate_policy_sha256=candidate['candidate_policy_sha256'],
                        parent_policy_sha256=protocol.current_policy,
                        disposition='freeze_existing_best_without_resampling_or_reexecution'))
                    if protocol.rounds:protocol.freeze()
                    else:protocol.stop_without_improvement('unchanged_candidate_no_resampling')
                    save_protocol(a,protocol)
                    break
                if protocol.budget.remaining==0:
                    raise StagePaused('learning_budget_wait_completed_trajectories_retained')
                protocol.propose(candidate['candidate_policy_sha256'])
                candidate_rows,candidate_paths=batch(a,'development',{'post':candidate_path})
                protocol.finish_round(parent_rows+candidate_rows)
                immutable_json(stage/'selection.json',protocol.rounds[-1])
                selected=candidate_path if protocol.current_policy==candidate['candidate_policy_sha256'] else parent
                save_protocol(a,protocol)
                if cycle==0:
                    previous_feedback=export_previous_development_feedback(
                        a.benchmark,cycle+1,read(parent),candidate,
                        {'pre':paths['pre'],'post':candidate_paths['post']},protocol.rounds[-1],
                        protocol.current_policy,stage/'development-feedback.json',run_trial.source_hashes())
            if protocol.phase=='no_improvement':
                selected=initial;protocol.select_parent_fallback();save_protocol(a,protocol)
            else:
                rows,_=batch(a,'validation',{'pre':initial,'post':selected})
                protocol.validate_once(rows);save_protocol(a,protocol)
                immutable_json(a.output/'reserved-validation.json',protocol.validation_result)
                if protocol.phase=='no_improvement':
                    selected=initial;protocol.select_parent_fallback();save_protocol(a,protocol)
            release(a,protocol,initial,selected)
            rows,_=batch(a,'test',{'native':initial,'post':selected})
            protocol.record_final_test(rows,run_trial.native_policy_hash());save_protocol(a,protocol)
            immutable_json(a.output/'study-complete.json',dict(status='complete',result=protocol.manifest()['final_result']))
            (a.output/'paused.json').unlink(missing_ok=True)
        except (StagePaused,ProposalPaused,ValueError) as error:
            save_protocol(a,protocol);write(a.output/'paused.json',dict(reason=str(error),error_type=type(error).__name__,
                  resample=False,capability_failure=False,completed_trajectories_retained=True));raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--benchmark',choices=['rmbench','remem'],required=True)
    p.add_argument('--gpu',type=int,choices=range(8),required=True);p.add_argument('--policy',type=Path,required=True)
    p.add_argument('--ledger',type=Path,required=True);p.add_argument('--qualification',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();asyncio.run(run(a))
if __name__=='__main__':main()
