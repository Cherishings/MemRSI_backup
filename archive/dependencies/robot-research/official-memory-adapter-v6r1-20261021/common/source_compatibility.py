import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ALLOWED={'common/visual_rule_proposal.py','common/source_compatibility.py',
         'common/test_proposal_pack_v5r2.py','run_study.py','learn_visual.py'}
def execution_source_matches(actual, expected):
    if actual == expected: return True
    audit=ROOT/'source-migration.json'
    if not audit.exists(): return False
    proof=json.loads(audit.read_text())
    if proof.get('current_source_hashes') != expected: return False
    if actual not in proof.get('prior_source_hashes', []): return False
    changed={k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k)}
    return bool(changed) and changed <= ALLOWED
