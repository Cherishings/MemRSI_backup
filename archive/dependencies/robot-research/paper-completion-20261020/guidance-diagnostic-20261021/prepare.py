"""Register all conditions before new outcomes; no model or physics calls."""
import argparse
import copy
import importlib.util
import json
import time
from pathlib import Path

ROOT=Path('/data/stormlab/xi/robot')
HERE=Path(__file__).resolve().parent
ARMS=('cap5_control','cap10','cadence2_full','cadence2_no_short')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output)
    spec=importlib.util.spec_from_file_location('cap',ROOT/'paper-supplement-20261018/capacity_robustness.py')
    cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
    if (out/'manifest.json').exists():raise RuntimeError('registration_already_exists')
    old=ROOT/'runs/paper-component-ablation-20261020';m=cap.read(old/'manifest.json')
    assert cap.source_identity(m['source'],m['core'])==m['source_identity']
    policy=cap.read(old/'frozen-policy.json');assert cap.digest(policy)==m['policy_sha256']
    plans=[j['plan'] for j in m['jobs'] if j['arm']=='no_guidance']
    assert len(plans)==48 and len({p['id'] for p in plans})==48
    jobs=[]
    # Rotate arm order, predeclared before any new outcome; all conditions kept.
    for i,trial in enumerate(plans):
        for arm in ARMS[i%4:]+ARMS[:i%4]:
            jobs.append({'key':arm+'/'+trial['id'],'arm':arm,'plan':copy.deepcopy(trial),
                         'condition_id':trial['id'],'replicate_block':'guidance-diagnostic-20261021'})
    code={p.name:cap.file_sha(p) for p in sorted(HERE.glob('*.py'))}
    manifest={
        'registered_at':time.time(),'source':m['source'],'core':m['core'],
        'source_identity':m['source_identity'],'policy_sha256':m['policy_sha256'],
        'code_sha256':code,'arms':list(ARMS),'jobs':jobs,'planned_new_trials':192,'trials_per_arm':48,
        'replicate_block':'guidance-diagnostic-20261021','learning_calls':0,
        'budget':{'persistent_tokens':1024,'active_input_tokens':12288,'output_tokens_per_call':2048,'calls_per_trial':480},
        'learning_ledger_changes':False,'same_physical_executor_and_scoring':True,
        'start_before_epoch':m['start_before_epoch'],
        'scope':'new predeclared stochastic replication block of ALL 48 previously inspected Casa conditions; not unseen scenes, not technical retries, not benchmark RSI evidence',
        'predecessor':str(old),'predecessor_manifest_sha256':cap.file_sha(old/'manifest.json'),
        'comparisons':[
            {'control':'cap5_control','treatment':'cap10','difference':'maximum evidence IDs 5 vs 10 only; exact 480-char fragments and global token budgets unchanged'},
            {'control':'cadence2_full','treatment':'cadence2_no_short','difference':'only G short-context argument, same every-second-boundary native archival cadence and intact actor short history'}],
        'cadence_limit':'Original session_switches field counts requested boundaries. Use diagnostic-boundaries/diagnostic-exposure for actual explicit archives and observed nonempty S; automatic native consolidation unchanged.',
        'primary_outcome':'all48 paired full-workflow success; success and capability/protocol failures retained; technical pairs reported separately with fixed denominator also reported',
        'secondary_outcomes':['paired discordance','actual nonempty short exposure','evidence-cap saturation','current-request inclusion','prompt and output token usage','boundary count and call cost'],
        'analysis_rule':'No favorable subset selection. If nonempty S contrast absent, report manipulation failure, not a causal effect. New outcomes never replace original results. No deployment selection from these diagnostic conditions.',
        'stop_rule':'first technical/unclassified failure blocks new dispatch; audit before any technical retry, lifetime max3; no automatic retries',
        'user_authorization':'2026-10-21 user explicitly requested thorough Guidance token/information checks, more experiments, and continuation after ablations while away; GPUs4/7 only',
        'original_no_short_arm_correction':'Original full48 Guidance S empty in584/584 calls; existing no_short arm is an equivalent-input replication control, not evidence of harmful short memory.'}
    cap.write(out/'frozen-policy.json',policy);cap.write(out/'manifest.json',manifest)
    identities={str(g):cap.read(old/f'worker-gpu{g}.json')['identity'] for g in (4,7)}
    cap.write(out/'relay-plan.json',{'predecessor':str(old),'predecessor_manifest_sha256':cap.file_sha(old/'manifest.json'),
        'predecessor_workers':identities,'gpus':[4,7],'bench_priority_gpus':[5,6],'forbidden_gpus':[0,1,2,3],
        'wait_for_all192_terminal_and_both_normal_worker_exits':True})
    print(json.dumps({'registered':str(out),'jobs':len(jobs),'policy_sha256':m['policy_sha256'],'predecessor_workers':identities}))

if __name__=='__main__':main()
