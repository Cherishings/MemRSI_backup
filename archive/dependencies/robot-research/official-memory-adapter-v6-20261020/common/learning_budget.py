"""Durable cumulative admission for all development/validation/proposal calls.

A charge is reserved before a logical model request. Network transport retries
inside that request do not charge again. Failed requests keep their reservation.
Evaluation calls use their own unchanged per-episode limit, not this ledger.
"""
import fcntl,json,os,time
from pathlib import Path
BASE_USED=8986
BASE_LIMIT=9745
class LearningBudgetExhausted(RuntimeError):pass

def charge(path, purpose, case_id):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with p.with_suffix('.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if not p.exists():
   d={'inherited_used':BASE_USED,'used':BASE_USED,'authorized_limit':BASE_LIMIT,'entries':[]}
  else:d=json.loads(p.read_text())
  if d.get('inherited_used')!=BASE_USED or d['used']<BASE_USED:raise RuntimeError('learning_ledger_inheritance_mismatch')
  if d['authorized_limit']!=BASE_LIMIT:
   approval=d.get('additional_authorization')
   if not isinstance(approval,dict) or not approval.get('user_message') or approval.get('total_limit')!=d['authorized_limit']:raise RuntimeError('learning_budget_authorization_missing')
  if d['used']>=d['authorized_limit']:raise LearningBudgetExhausted('learning_budget_exhausted')
  d['used']+=1;d['entries'].append({'sequence':d['used'],'purpose':purpose,'case_id':case_id,'reserved_unix':time.time()})
  q=p.with_suffix('.tmp');q.write_text(json.dumps(d,indent=2)+'\n');os.replace(q,p)
  return d['used']
