"""Offline reference semantics on explicitly normalized inputs, not a runtime parser.
Human-authored; does not infer authority, scope or completeness from natural language.
"""
from copy import deepcopy

def apply_receipt(state, decision, receipt):
    if set(decision) != {'id','entity','obligation'} or set(receipt) != {'decision_id','entity','obligation','completed_components'}:
        raise ValueError('shape')
    if receipt['decision_id'] != decision['id'] or any(receipt[k] != decision[k] for k in ('entity','obligation')):
        raise ValueError('uncorrelated_receipt')
    key=(decision['entity'],decision['obligation'])
    if key not in state: raise ValueError('unknown_obligation')
    completed=receipt['completed_components']
    if type(completed) is not list or any(type(v) is not str for v in completed) or len(set(completed)) != len(completed):
        raise ValueError('component_shape')
    old=state[key]
    if set(old) != {'required','completed'} or not set(old['completed']) <= set(old['required']):
        raise ValueError('invalid_state')
    if not set(completed) <= set(old['required']): raise ValueError('scope_expansion')
    result=deepcopy(state)
    result[key]['completed']=sorted(set(old['completed']) | set(completed))
    return result

def is_complete(item):
    return bool(item['required']) and set(item['required']) <= set(item['completed'])
