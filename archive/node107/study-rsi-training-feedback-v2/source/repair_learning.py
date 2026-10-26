"""Reuse identical-policy development attempts; repair only unexecuted updates."""
import hashlib,json,shutil
from pathlib import Path
from durable_queue import read
from memory_policy import digest
from parallel_runtime import ParallelExperiment
from replay import dump

class RepairExperiment(ParallelExperiment):
    def __init__(self,*args,old_learning,**kwargs):
        super().__init__(*args,**kwargs);self.old_learning=Path(old_learning)
    def batch(self,rows,policies,output,strict_technical=False,inherited=()):
        output=Path(output);extra=[];same=False
        if output.name=='physical' and output.parent.name.startswith('round-'):
            old=self.old_learning/output.parent.name
            policy=read(policies['memrsi']);previous=read(old/'parent-policy.json')
            same=previous is not None and digest(previous)==digest(policy)
            if same:
                # Includes every original attempt, including failures and exhausted cases.
                extra=[dict(r,inherited=True,inherited_policy_sha256=digest(policy)) for r in read(old/'physical/attempts.json',[])]
            output.mkdir(parents=True,exist_ok=True)
            dump(output/'reuse-audit.json',{'source':str(old),'same_parent_policy':same,
                 'inherited_attempts':len(extra),'attempt_limit_unchanged':3,
                 'new_policy_new_treatment':previous is not None and not same,
                 'test_outcomes_read':False})
        return super().batch(rows,policies,output,strict_technical,inherited=tuple(inherited)+tuple(extra))

def initialize_repair(old,new):
    old=Path(old);new=Path(new);new.mkdir(parents=True,exist_ok=True)
    marker=new/'repair-origin.json'
    if marker.exists():return
    if (new/'learning-call-ledger.json').exists():raise RuntimeError('partial_repair_init_requires_audit')
    ledger=read(old/'learning-call-ledger.json',{'calls':0,'limit':6000})
    dump(new/'learning-call-ledger.json',ledger)
    first=read(old/'round-0/decision.json')
    if not first or first['accepted']:raise RuntimeError('unexpected_first_round_requires_audit')
    # First proposal and its completed rejection were validly executed. Do not
    # regenerate it to search for a better random outcome.
    for name in ('decision.json','parent-policy.json'):
        p=new/'round-0'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((old/'round-0'/name).read_bytes())
    dump(marker,{'source_learning':str(old),'old_optimizer_calls_counted':ledger['calls'],
       'first_round_decision_retained':True,'failed_context_rounds_reexecuted':True,
       'initial_input_target':9000,'hard_input_limit':12288,'per_trial_attempt_limit':3,
       'all_physical_failures_preserved':True,'fixed_and_native_outcomes_not_read':True,
       'old_optimizer_evidence_retained':True})
