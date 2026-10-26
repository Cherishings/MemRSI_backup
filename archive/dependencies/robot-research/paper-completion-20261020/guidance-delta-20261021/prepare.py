"""Register a manual G comparison without any model or physical calls."""
import copy,importlib.util,json,time
from pathlib import Path
from interventions import ARMS,candidate_policy
ROOT=Path('/data/stormlab/xi/robot');HERE=Path(__file__).resolve().parent
OUT=ROOT/'runs/paper-completion-20261020/guidance-delta-20261021'
spec=importlib.util.spec_from_file_location('cap',ROOT/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
def main():
 if OUT.exists():raise RuntimeError('existing_registration_requires_audit')
 old=ROOT/'runs/paper-completion-20261020/guidance-diagnostic-20261021';m=cap.read(old/'manifest.json');p=cap.read(old/'frozen-policy.json')
 assert cap.digest(p)==m['policy_sha256'] and cap.source_identity(m['source'],m['core'])==m['source_identity']
 plans=[j['plan'] for j in m['jobs'] if j['arm']=='cap5_control'];assert len(plans)==48 and len({p['id'] for p in plans})==48
 jobs=[]
 for i,plan in enumerate(plans):
  for arm in ARMS[i%2:]+ARMS[:i%2]:jobs.append({'key':arm+'/'+plan['id'],'arm':arm,'plan':copy.deepcopy(plan),'condition_id':plan['id'],'replicate_block':'guidance-delta-20261021'})
 new=copy.deepcopy({k:m[k] for k in ('source','core','source_identity','policy_sha256','budget','start_before_epoch')})
 new.update(registered_at=time.time(),jobs=jobs,arms=list(ARMS),planned_new_trials=96,trials_per_arm=48,replicate_block='guidance-delta-20261021',code_sha256={p.name:cap.file_sha(p) for p in sorted(HERE.glob('*.py'))},learning_calls=0,learning_ledger_changes=False,predecessor=str(old),predecessor_manifest_sha256=cap.file_sha(old/'manifest.json'),same_physical_executor_and_scoring=True,
 effective_policy_sha256={ARMS[0]:cap.digest(p),ARMS[1]:cap.digest(candidate_policy(p))},
 scope='Manual design follow-up on all48 previously inspected Casa conditions, new replication block; not unseen scenes, not RSI learning or generalization evidence.',
 primary_outcome='Paired full-workflow success across all48; fixed-denominator results plus valid-pair results, technical failures separately; all negative outcomes retained.',
 secondary_outcomes=['paired wins/losses','nonempty S exposure per arm','selected source fragments and empty selection rate','input/output tokens and calls','failure stages'],
 comparison='Only G procedure changes; both arms cadence2 real S, cap5 exact source IDs, actor full MEMORY/history access, U and executor identical.',
 stop_rule='First technical/unclassified blocks dispatch; no automatic retry; audit lifetime max3. No outcome-dependent extra trials or policy tuning.',
 analysis_rule='One prespecified all48 comparison. No selection of favorable conditions. Exposures must verify both arms receive genuine S; report manipulation failure otherwise. Completed results do not replace old results. Any future validation must use separately untouched conditions.',
 user_authorization='User requested independent strengthening of weak Guidance and recursive learning; existing explicit GPU1-7 permission, GPU0 reserved. This is a manual G experiment with zero learning calls.',
 gpus=[1,2,3,4,7],benchmark_priority_gpus=[5,6],forbidden_gpus=[0])
 cap.write(OUT/'frozen-policy.json',p);cap.write(OUT/'manual-candidate-policy.json',candidate_policy(p));cap.write(OUT/'manifest.json',new)
 print(json.dumps({'registered':str(OUT),'trials':96,'manual_not_RSI':True,'learning_calls':0}))
if __name__=='__main__':main()
