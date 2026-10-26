"""Environment-neutral mission metrics. Scorer-private expectations never enter actors.
Adapters export the schema below; this does NOT implement RoboTwin/RoboDojo control.
"""
import argparse,json,math
from pathlib import Path

def rate(n,d):
    if not d:return {'numerator':n,'denominator':d,'value':None,'wilson95':None}
    z=1.959963984540054;p=n/d;den=1+z*z/d
    center=(p+z*z/(2*d))/den;half=z*math.sqrt(p*(1-p)/d+z*z/(4*d*d))/den
    return {'numerator':n,'denominator':d,'value':p,'wilson95':[max(0,center-half),min(1,center+half)]}

def normalize_libero(r):
    ds=r.get('decisions',[]);xs=r.get('physical_executions',[])
    checkpoints=[d for d in ds if d['stage'].startswith('return_') or d['stage']=='finish']
    return {'schema':'mission-eval-v0.1','environment':'LIBERO','status':r['status'],
        'case':r['case'],'history':r['history'],'length_jobs':r['intermediate_jobs'],
        'planned_checkpoints':r['planned_checkpoint'],'reached_checkpoints':r['arrived_checkpoint'],
        'answered_checkpoints':r['answered_checkpoint'],'correct_checkpoints':r['correct_checkpoint'],
        'checkpoint_choices':[{'id':d['stage'],'action':d['choice']['skill'],'expected_private':d['expected'],'correct':d['correct']} for d in checkpoints],
        'recovery_snapshot':r.get('recovery_snapshot'),
        'valid_trajectory':r['status']=='success',
        'action_selection_errors':len(r.get('decision_errors',[])),
        'error_forms':r.get('memory_error_forms',[]),
        'physical_attempts':len(xs),'physical_successes':sum(x['result']['success'] is True for x in xs),
        'distance':{'completed_kitchen_jobs':sum(x['skill']=='execute_order' and x['result']['success'] for x in xs),
                    'session_switches':len(r.get('rollovers',[])),
                    'model_calls':r.get('model_calls'), 'input_tokens':r.get('model_input_tokens'),
                    'output_tokens':r.get('model_output_tokens')},
        'state_source':'privileged symbolic simulator observations shared equally by all arms; not a perception benchmark',
        'arm':r.get('arm'),'init':r.get('init'),'variant':r.get('variant')}

def validate(r):
    if r['schema']!='mission-eval-v0.1':raise ValueError('metric_schema')
    p,n,a,c=(r[k] for k in ('planned_checkpoints','reached_checkpoints','answered_checkpoints','correct_checkpoints'))
    if not all(isinstance(x,int) and x>=0 for x in (p,n,a,c)) or not 0<=c<=a<=n<=p:raise ValueError('checkpoint_counts')
    if not 0<=r['physical_successes']<=r['physical_attempts']:raise ValueError('physical_counts')

def information_pair(a,b):
    aa,bb=a.get('recovery_snapshot'),b.get('recovery_snapshot')
    if not aa or not bb:return {'both_reached':False,'history_required':None,'paired_correct':False}
    same=(aa['current_input_sha256']==bb['current_input_sha256'] and aa['station_state_sha256']==bb['station_state_sha256']
          and aa.get('action_contract_sha256')==bb.get('action_contract_sha256'))
    different=aa.get('expected_first_private') is not None and aa.get('expected_first_private')!=bb.get('expected_first_private')
    choices=[r.get('checkpoint_choices',[]) for r in (a,b)]
    return {'both_reached':True,'same_observation_and_request':same,'different_required_actions':different,
        'history_required':bool(same and different),'paired_correct':bool(same and different and all(x and x[0]['correct'] for x in choices))}

def summarize(records,planned_trials=None):
    for r in records:validate(r)
    p=sum(r['planned_checkpoints'] for r in records);n=sum(r['reached_checkpoints'] for r in records)
    c=sum(r['correct_checkpoints'] for r in records);a=sum(r['answered_checkpoints'] for r in records)
    result={'terminal_trials':len(records),'planned_trials':planned_trials,
        'checkpoint_coverage':rate(n,p),'correct_at_reached':rate(c,n),
        'correct_at_answered':rate(c,a),'correct_over_planned':rate(c,p),
        'whole_workflow_success':rate(sum(r['valid_trajectory'] for r in records),len(records)),
        'physical_execution_success':rate(sum(r['physical_successes'] for r in records),sum(r['physical_attempts'] for r in records)),
        'status_counts':{s:sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})},
        'note':'Checkpoint/physical Wilson intervals are descriptive and ignore within-episode dependence. Do not use them for method-significance claims; use paired episode-level inference.'}
    case_rates={}
    for case in sorted({r['case'] for r in records}):
        rs=[r for r in records if r['case']==case];reached=[r for r in rs if r['reached_checkpoints']]
        case_rates[case]={'incomplete_or_wrong_recovery_over_reached_episodes':rate(sum(r['correct_checkpoints']<r['planned_checkpoints'] for r in reached),len(reached)),
            'reached_episodes':len(reached),'terminal_episodes':len(rs),'error_forms':{f:sum(f in r['error_forms'] for r in rs) for f in sorted({f for r in rs for f in r['error_forms']})}}
    result['by_case']=case_rates
    groups={}
    for r in records:groups.setdefault((r.get('arm'),r['case'],r['length_jobs'],r.get('init'),r.get('variant')), {})[r['history']]=r
    pairs=[information_pair(g['one_first'],g['two_first']) for g in groups.values() if set(g)=={'one_first','two_first'}]
    result['history_pairs']={'terminal_pairs':len(pairs),'auditable_pairs':sum(p['history_required'] is True for p in pairs),
        'pair_success_over_terminal_pairs':rate(sum(p['paired_correct'] for p in pairs),len(pairs)),
        'pair_success_over_history_required_pairs':rate(sum(p['paired_correct'] for p in pairs),sum(p['history_required'] is True for p in pairs)),
        'details':pairs}
    return result


def learning_gain(before, after):
    """Matched held-out outcomes; never call interface repair a learned effect."""
    def key(r):return (r['environment'],r['case'],r['history'],r['length_jobs'],r.get('init'),r.get('variant'))
    left,right={key(r):r for r in before},{key(r):r for r in after}
    shared=sorted(left.keys() & right.keys())
    improved=sum(not left[k]['valid_trajectory'] and right[k]['valid_trajectory'] for k in shared)
    regressed=sum(left[k]['valid_trajectory'] and not right[k]['valid_trajectory'] for k in shared)
    return {'matched_terminal_scenarios':len(shared),'improved':improved,'regressed':regressed,
        'success_rate_difference':(improved-regressed)/len(shared) if shared else None,
        'pairs_with_infrastructure_failure':sum(any(x['status']=='infrastructure_failure' for x in (left[k],right[k])) for k in shared),
        'before_unmatched':len(left.keys()-right.keys()),'after_unmatched':len(right.keys()-left.keys()),
        'interpretation':'Only frozen-before/frozen-after rules on excluded test histories measure learning gain. Report regressions and matching coverage. No significance claim from this pilot.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('records',nargs='+');a=p.parse_args()
    records=[json.loads(Path(x).read_text()) for x in a.records]
    print(json.dumps(summarize(records),ensure_ascii=False,indent=2))
