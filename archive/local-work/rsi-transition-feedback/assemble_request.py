import json,sys
from pathlib import Path
from paired import build_view
from request_view import assemble
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'rsi-process-edit-v1'))
import learn
from runtime_contract import extract
from anchor_catalog import schema_for
from process_scope import SCOPE
parent=json.loads((ROOT.parent/'rsi-typed-process-prototype/parent-policy.json').read_text())
parent_text={k:json.loads(parent[k])['procedure'] for k in ('guidance','update')}
schema=schema_for(parent_text,learn.JOINT_SCHEMA)
audit=json.loads((ROOT.parent/'heartbeat-1021/mechanism-audit.json').read_text())
# Prior training audit, retaining all eight output-limit records and observed malformed response facts.
diagnostics={'output_limits':audit['output_limits'],'protocol_failure':audit['protocol_failure'],'limits':audit['limits']}
view=build_view(json.loads((ROOT/'training-transitions.json').read_text()))
system=learn.JOINT_SYSTEM+SCOPE+' Use the supplied training archive before/after transitions and public messages to propose one joint local process edit against the ORIGINAL parent. Preserve the existing runtime, actor authority, native archival call, save_memory tool, budgets and critic standards. The evidence includes all32 summaries, one latest common-event archive per arm in each source/repeat and an explicitly selected known training error. Shared events do not imply identical model histories. Geometry omissions are explicitly marked. Archive success is not semantic correctness; source_error_corrected is not full task success. No omitted evidence may be treated as proof of absence. Memory lines are exact indexed text, not an inferred state table. Do not invent additional examples, task identities or action answers in the rule. Return a new generic process proposal; do not repeat prior candidates or restate output schema constraints as a learned change.'
request=assemble(view,parent_text,schema,extract(ROOT.parent/'rsi-process-edit-v1/method.py'),diagnostics,system)
(ROOT/'full-request.json').write_text(json.dumps(request,ensure_ascii=False,separators=(',',':')))
print({'bytes':(ROOT/'full-request.json').stat().st_size,'messages':len(request['messages'])})
