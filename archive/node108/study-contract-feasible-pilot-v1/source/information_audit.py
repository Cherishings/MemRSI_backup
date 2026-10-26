"""Audit current-only identifiability without querying or modifying any actor."""
import argparse,json
from pathlib import Path
from portable_metrics import information_pair

def audit(source):
    groups={}
    for p in sorted(Path(source).glob('discovery/*/result.json')):
        d=json.loads(p.read_text());s=d.get('recovery_snapshot')
        first=next((c for c in d.get('decisions',[]) if c['stage']=='return_1'),None)
        if s and first:s=dict(s,expected_first_private=first['expected'],action_contract_sha256='same-recorded-adapter-version')
        groups.setdefault((d['case'],d['intermediate_jobs'],d['init']),{})[d['history']]={'recovery_snapshot':s,'checkpoint_choices':[{'correct':first['correct']}] if first else []}
    pairs=[]
    for (case,jobs,init),g in groups.items():
        if set(g)=={'one_first','two_first'}:pairs.append(dict(case=case,jobs=jobs,init=init,**information_pair(g['one_first'],g['two_first'])))
    return {'source':str(source),'scope':'Task-facing scene/request equality; original shared adapter assumed common within a paired experiment. Historical memory is deliberately different.',
        'pairs':pairs,'planned_pairs':len(groups),'terminal_pairs':len(pairs),
        'identical_now_different_required_action_pairs':sum(p['history_required'] is True for p in pairs),
        'nonidentical_now_pairs':sum(p.get('same_observation_and_request') is False for p in pairs),
        'interpretation':'Identical present with different valid answers establishes historical information necessity. Nonidentical present does not prove memory was unnecessary, but cannot exclude visual shortcuts.'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--output');a=p.parse_args();r=audit(a.source);s=json.dumps(r,ensure_ascii=False,indent=2)
    if a.output:Path(a.output).write_text(s)
    else:print(s)
