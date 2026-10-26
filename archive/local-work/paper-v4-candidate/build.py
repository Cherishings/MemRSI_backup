"""Prepare an unlaunched manual parent from observed development failures."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
parent = json.loads((root / 'previous-parent.json').read_text())
guidance = (
    'Audit the next action using only supplied public evidence and the execution catalog. '
    'First extract the latest request target and operation in its own terms. Separate the target entity '
    'from contextual words such as job or work. Then recover any still-active originating request, '
    'continuation trigger, ordering revision and cancellation. A continuation can activate an earlier '
    'authorization without issuing a new request. Match the target entity and requested operation '
    'against the candidate catalog scope AND its prerequisites. Reject a candidate when its scope '
    'excludes the requested entity even if contextual words sound similar. Do not infer the task '
    'category merely from the word job. Correlate receipts with the exact submitted action and '
    'target; partial success does not discharge the remaining obligation. Before recommending '
    'termination, check every authorized pending or suspended obligation and its trigger, including '
    'conditional final work. Do not interpret missing recent mention as cancellation. '
    'In the recommendation use four compact labeled fields: Target (request entity/operation), '
    'Authority (origin or continuation evidence), Match (candidate scope and satisfied prerequisite), '
    'Action (one recommendation or abstain). In uncertainty name the strongest conflicting evidence '
    'or unmet prerequisite; do not invent one. Cite the supporting evidence IDs. Treat memory as '
    'fallible: prefer explicit public requests and correlated receipts over summary assertions. '
    'Never execute, veto, invent evidence, or use private evaluator information. The actor decides.'
)
update = (
    'Consolidate public requests and correlated execution receipts into a compact obligation ledger '
    'in the existing memory text. Preserve for each live obligation: origin event, target, requested '
    'operation, activation or continuation condition, current ordering and revision event, status, '
    'and latest correlated receipt. Record conditional future work as authorized but waiting for its '
    'stated condition, not unauthorized. Distinguish authorization from readiness and completion. '
    'Carry forward the originating authorization and continuation trigger across unrelated intervening '
    'work. A short continuation request need not repeat the original authorization. Remove an '
    'obligation only on an explicit applicable cancellation or a receipt proving its requested extent '
    'complete. One successful segment leaves the remainder pending when the request requires more. '
    'A submitted action is only a commitment until the correlated receipt. A revision changes only '
    'its stated scope; retain the original ordering needed to resolve relative references. '
    'Before saving, check each previously pending or conditional obligation: either retain it with '
    'its trigger, or cite the cancellation/completion event that discharges it. Never turn an actor '
    'assumption about authorization into a user restriction. Preserve unresolved conflicts as uncertain. '
    'Within the shared memory budget prioritize live obligations and evidence IDs over coordinates '
    'or verbose completed-job descriptions; compact discharged jobs. Do not invent a plan, task, '
    'restriction, dependency or completion. History records the actual change and its evidence.'
)
parent['guidance'] = json.dumps({'kind':'procedure_guidance_v2','procedure':guidance}, sort_keys=True)
parent['update'] = json.dumps({'kind':'procedure_update_v2','procedure':update}, sort_keys=True)
assert len(guidance) <= 4096 and len(update) <= 4096
path = root / 'candidate-parent.json'
path.write_text(json.dumps(parent, indent=2)+'\n')
record = {
    'state':'candidate_only_not_launched', 'manual_parent_not_RSI':True,
    'development_evidence':['hEDABC-v1-i0/g_only/event21', 'hEDABC-v1-i0/u_only/events1-30'],
    'changes':['G requires explicit target, authority and catalog scope match',
               'U preserves live obligations, authorization and continuation triggers'],
    'unchanged_requirements':['same call counts and budgets across matched controls',
                              'preserve current frozen run and all failures/costs',
                              'no test feedback used', 'no runtime action veto or answer injection'],
    'candidate_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
    'next_gate':'complete current first-condition comparisons and register technical replacements for infrastructure-only missing cells before launching a new parent comparison',
}
(root/'candidate-status.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
