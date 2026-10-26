"""Operational parallel episode reservations in the existing cumulative ledger."""
import fcntl,json,os,time,hashlib
from pathlib import Path
from contextlib import contextmanager

def identity():return {'pid':os.getpid(),'start_ticks':Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')',1)[1].split()[19]}
def alive(row):
 try:
  a=Path(f'/proc/{row["pid"]}/stat').read_text().rsplit(')',1)[1].split();return a[0]!='Z' and a[19]==str(row['start_ticks'])
 except (FileNotFoundError,KeyError):return False
def write(p,d):
 q=p.with_name(p.name+'.parallel-tmp.'+str(os.getpid()));q.write_text(json.dumps(d,indent=2)+'\n');q.replace(p)
@contextmanager
def ledger(path):
 p=Path(path)
 with p.with_suffix('.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);d=json.loads(p.read_text())
  if d.get('inherited_used')!=8986 or d['used']<8986:raise RuntimeError('learning_ledger_inheritance_mismatch')
  approval=d.get('additional_authorization',{})
  if d['authorized_limit']!=9745 and (not approval.get('user_message') or approval.get('total_limit')!=d['authorized_limit']):raise RuntimeError('learning_budget_authorization_missing')
  yield p,d

def available(d):return d['authorized_limit']-d['used']-sum(x['remaining'] for x in d.get('episode_reservations',{}).values())
def settled(row):
 if alive(row['identity']):return False
 p=Path(row['output'])/'child-processes.json'
 if p.exists() and any(alive(x['identity']) for x in json.loads(p.read_text())):return False
 return True

def install_charge(m):
 def charge(path,purpose,case_id):
  with ledger(path) as (p,d):
   rs=d.get('episode_reservations',{})
   matches=[v for v in rs.values() if v['case_id']==case_id and not v.get('legacy') and alive(v['identity'])]
   if len(matches)>1:raise RuntimeError('ambiguous_episode_reservation')
   owned=matches[0] if matches else None
   if d['used']>=d['authorized_limit'] or (owned is not None and owned['remaining']<=0) or (owned is None and available(d)<=0):raise m.LearningBudgetExhausted('learning_budget_exhausted')
   if owned is not None:owned['remaining']-=1
   d['used']+=1;d['entries'].append({'sequence':d['used'],'purpose':purpose,'case_id':case_id,'reserved_unix':time.time()});write(p,d);return d['used']
 m.charge=charge

def install_admission(rt):
 @contextmanager
 def admission(args):
  if args.phase=='test':yield True;return
  path=Path(args.ledger);rid=hashlib.sha256(str(args.output.resolve()).encode()).hexdigest()
  # One lane per benchmark; original ordering within a benchmark remains serial.
  with path.with_suffix('.parallel-'+args.benchmark+'.lock').open('a') as lane:
   fcntl.flock(lane,fcntl.LOCK_EX)
   with ledger(path) as (p,d):
    rs=d.setdefault('episode_reservations',{})
    for k,v in list(rs.items()):
     if settled(v):d.setdefault('closed_episode_reservations',[]).append(dict(rs.pop(k),closed_unix=time.time()))
    remaining=available(d);admitted=remaining>=480
    if admitted:
     if rid in rs:raise RuntimeError('duplicate_episode_reservation')
     rs[rid]={'identity':identity(),'output':str(args.output.resolve()),'case_id':args.benchmark+':'+str(args.seed)+':'+args.method,'remaining':480,'capacity':480,'legacy':False,'time':time.time()}
    write(p,d)
   if not admitted:
    note={'phase':'waiting_learning_budget','remaining_unreserved':remaining,'required_episode_capacity':480,'attempt_started':False,'time':time.time()};rt.write(args.output/'waiting-learning-budget.json',note);rt.write(args.output/'progress.json',note);yield False;return
   args._learning_admission_fd=lane.fileno()
   rt.write(args.output/'parallel-admission.json',{'reservation_id':rid,'capacity':480,'ledger':str(path),'identity':identity(),'operational_only':True})
   try:yield True
   finally:
    del args._learning_admission_fd
    children=args.output/'child-processes.json'
    safe=not children.exists() or all(not alive(x['identity']) for x in json.loads(children.read_text()))
    if safe:
     with ledger(path) as (p,d):
      row=d.get('episode_reservations',{}).pop(rid,None)
      if row:d.setdefault('closed_episode_reservations',[]).append(dict(row,closed_unix=time.time()))
      write(p,d)
 rt.learning_admission=admission
