"""Exact historical regression cache only; no request, retry, or proposal reuse."""
import hashlib,json
from pathlib import Path

def read(p):return json.loads(Path(p).read_text())
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def reuse_regression(path,out,old,system,data,schema,signature):
 from transition_diagnosis import DIAG_SYSTEM,DIAG_SCHEMA,validate_diagnosis
 from protocol import immutable_write
 from budget_account import atomic_json
 rel=path.relative_to(out)
 parts=rel.parts
 if len(parts)!=5 or parts[:2]!=('cycle-1','diagnosis') or not parts[2].startswith('regression-') or parts[4]!='diagnosis':
  raise RuntimeError('old_optimizer_request_requires_audit')
 if system!=DIAG_SYSTEM or schema!=DIAG_SCHEMA or data.get('role')!='previous_rejected_candidate_regression':
  raise RuntimeError('old_optimizer_request_requires_audit')
 prior=old/rel;evidence=prior.parent/'evidence.json';valuepath=prior/'value.json';request=prior/'request-identity.json'
 if not all(p.is_file() for p in (evidence,valuepath,request)) or (prior/'candidate-rejection.json').exists():
  raise RuntimeError('old_optimizer_request_requires_audit')
 actual=hashlib.sha256(json.dumps([system,data,schema],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 if actual!=signature or read(request)['sha256']!=signature or read(evidence)!=data:
  raise RuntimeError('historical_regression_identity_changed')
 value=read(valuepath)
 # Format and evidence failures remain failures under the unchanged caller.
 import jsonschema
 jsonschema.validate(value,schema)
 quote_valid=True;rejection=None
 try:validate_diagnosis(value,data['documents'])
 except ValueError as e:quote_valid=False;rejection=str(e)
 record=dict(request_sha256=signature,source=str(prior),source_value_sha256=digest(valuepath),source_evidence_sha256=digest(evidence),source_request_sha256=digest(request),original_attempts=sorted(p.name for p in prior.glob('attempt-*')),quote_valid=quote_valid,original_quote_rejection=rejection,new_calls=0,scope='unchanged historical regression diagnostic only; original caller validates quotes',proposal_or_candidate_reused=False)
 immutable_write(path/'historical-cache-reuse-r2.json',record,atomic_json)
 return value
