"""Extract citation interface evidence from registered training, never task answers."""
import hashlib
import json
from pathlib import Path

def classify(args, allowed):
    ids = args.get('basis_ids')
    if not isinstance(ids, list): return 'not_array'
    if len(ids) > 5: return 'too_many'
    if any(not isinstance(x, str) or x not in allowed for x in ids): return 'outside_source_enum'
    if len(ids) != len(set(ids)): return 'duplicate'
    if str(args.get('recommendation', '')).strip() and not ids: return 'missing_nonempty_recommendation_basis'
    return 'valid_citation'

def collect(replay, allowed_root):
    replay, allowed_root = Path(replay).resolve(), Path(allowed_root).resolve()
    assert replay.is_relative_to(allowed_root), 'Nontraining trace rejected'
    path = replay/'model-trace.jsonl'
    out = {'replay':str(replay), 'schemas':[], 'counts':{}, 'examples':[]}
    if not path.exists():
        out['trace_missing'] = True
        return out
    assert path.resolve().is_relative_to(allowed_root), 'Nontraining trace rejected'
    out['trace_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    seen = set()
    for line in path.read_text().splitlines():
        d = json.loads(line)
        for tool in d.get('request', {}).get('tools', []):
            f = tool.get('function', {})
            if f.get('name') != 'report_advice': continue
            schema = f['parameters']
            if schema not in out['schemas']: out['schemas'].append(schema)
            idx = out['schemas'].index(schema)
            allowed = schema['properties']['basis_ids']['items']['enum']
            for call in d.get('response', {}).get('tool_calls') or []:
                if call.get('name') != 'report_advice' or not isinstance(call.get('arguments'), dict): continue
                args = call['arguments']; reason = classify(args, allowed)
                out['counts'][reason] = out['counts'].get(reason, 0) + 1
                key = (idx, reason)
                if key not in seen:
                    seen.add(key)
                    out['examples'].append({'call':d['call'], 'schema_index':idx, 'classification':reason,
                        'basis_ids':args.get('basis_ids'), 'recommendation_nonempty':bool(str(args.get('recommendation','')).strip())})
    return out
