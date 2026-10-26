"""Two separately editable procedures; no task instance or expected answer lives here."""
import copy
import hashlib
import json
import re
from pathlib import Path

EMPTY = {'schema': 1, 'guidance': '', 'update': ''}
from memory_design import policy as design_policy, SEED, update_instruction
BASE = design_policy(SEED)



def validate(p):
    if not isinstance(p, dict) or set(p) != set(EMPTY) or p['schema'] != 1:
        raise ValueError('policy_schema')
    if any(not isinstance(p[k], str) or len(p[k]) > 32768 for k in ('guidance', 'update')):
        raise ValueError('policy_length')
    return copy.deepcopy(p)


def load(path=None):
    return validate(json.loads(Path(path).read_text()) if path else EMPTY)


def digest(p):
    return hashlib.sha256(json.dumps(validate(p), sort_keys=True).encode()).hexdigest()


def archive_request(kwargs, policy):
    names = {t.get('function', {}).get('name') for t in kwargs.get('tools', [])}
    if names not in ({'save_memory'}, {'pack_storage'}) or not policy['update']:
        return kwargs
    result = copy.deepcopy(kwargs)
    system = next(m for m in result['messages'] if m.get('role') == 'system')
    system['content'] += ('\n\nUpdate procedure for the long/short memory interface. '
                          'This is a general procedure, not an additional user mission:\n' + update_instruction(policy['update']))
    return result


def combinations(parent, candidate):
    p, c = validate(parent), validate(candidate)
    return {'old': p, 'update_only': dict(p, update=c['update']),
            'guidance_only': dict(p, guidance=c['guidance']), 'joint': c}


def screen(p):
    """Conservative lexical screen, followed by an independent model critic.

    This cannot prove absence of encoded answers. Every accepted policy remains
    inspectable and the final physical tasks are never exposed to the proposer.
    """
    validate(p)
    text = p['guidance'] + '\n' + p['update']
    forbidden = [r'serve_table', r'execute_order', r'table (?:one|two|1|2)',
                 r'kitchen', r'libero', r'butter', r'cheese', r'ketchup',
                 r'\b(?:12|16|24)\b', r'expected_remaining', r'correct_checkpoint',
                 r'/data/', r'benchmark', r'system prompt', r'ignore.*user']
    matches = [x for x in forbidden if re.search(x, text, re.I)]
    if matches:
        raise ValueError('task_specific_or_unsafe_policy')
    return True


def choose_smallest(scores, parent_key='old'):
    """Best paired gain, then fewest changed arrows; validation is separate.

    scores map variant -> {'passed': [bool,...], 'tokens': int}. Every case is
    paired. No previously correct case may regress, and one must improve.
    """
    base = scores[parent_key]['passed']
    eligible = []
    for name in ('update_only', 'guidance_only', 'joint'):
        row = scores[name]
        if len(row['passed']) != len(base):
            raise ValueError('unpaired_selection')
        gain = sum(row['passed']) - sum(base)
        eligible_failures = scores[parent_key].get('decision_failure', [not x for x in base])
        memory_gain = sum(f and passed for f, passed in zip(eligible_failures,row['passed']))
        regressions = sum(a and not b for a, b in zip(base, row['passed']))
        # Equal token budgets per request; also bound aggregate inference growth.
        if gain > 0 and memory_gain > 0 and regressions == 0 and row['tokens'] <= max(1, scores[parent_key]['tokens']) * 1.5:
            eligible.append((-(gain), int(name == 'joint'), row['tokens'], name))
    return sorted(eligible)[0][-1] if eligible else 'old'


def operator_credit(scores):
    s = {k: sum(v['passed']) / max(1, len(v['passed'])) for k, v in scores.items()}
    return {'update_effect': s['update_only'] - s['old'],
            'guidance_effect': s['guidance_only'] - s['old'],
            'interaction': s['joint'] - s['update_only'] - s['guidance_only'] + s['old'],
            'scope': 'paired intervention effects on replay behavior, not internal neural causality'}
