"""Two development cycles: actual transactional memory feedback -> learned G/U -> replay.
Native/fixed heldout results are never exposed here. Engineering changes are not
counted as learned improvements: both parent and candidate use DeltaStore.
"""
import asyncio,copy,json
from pathlib import Path
from durable_queue import read
from replay import dump
from delta_design import SEED,compile_policy
from delta_memory import encode
from trajectory_evolution import paired,select
from trajectory_replay import fixture,lines
from targeted_requests import cached_structured
from optimizer_context import clip,prepare
from stream_design import SCHEMA
from structured_feedback import CRITIC
from feedback_learning import screen_generic
from model_provider import LEARNING_LEDGER

SYSTEM=('Improve the Guidance and/or Update policy of an evidence-transaction memory agent. '
 'Requirements and progress are separate; transactions have exact source citations and revisions. '
 'The program validates syntax, provenance and capacity, not task meaning. '
 'Analyze FIRST actual errors and successful controls. Distinguish wrong archival edits, '
 'wrong evidence selection and actor misuse. Preserve working behavior; avoid repeatedly rewriting '
 'unrelated rules. Return complete guidance and update procedures, each <=1600 characters, and rationale. '
 'No concrete task, object, table, benchmark, order, event IDs or expected tool answers. '
 'No compulsory continuation/finish or hidden scoring access. These rules must generalize to new tasks.')


def fixtures_from(prior,cycle):
 root=Path(prior)/'learning'/f'cycle-{cycle}'/'probes';m=read(root/'manifest.json');rows=read(root/'rows.json');out=[]
 for s in m['sources']:
  r=next(x for x in rows if x['case']==s['id'] and x['policy']=='parent')
  f=fixture(r['source']);f['id']=s['id']
  if f['sha256']!=s['sha256']:raise RuntimeError('source_changed')
  out.append(f)
 return out


def packet(parent,root,rows,credits):
 evidence=[]
 for r in rows:
  d=Path(root)/f"{r['case']}-r{r['repeat']}-parent"/f"attempt-{r['attempts']:02d}"
  changes=lines(d/'delta-updates.jsonl');guides=lines(d/'guidance-events.jsonl')
  first=next((x for x in r.get('decisions',[]) if not x['correct']),None)
  guide=next((g for g in guides if first and g['current_request'].startswith(f"Event {first['event']}:")),guides[0] if guides else {})
  change=next((c for c in reversed(changes) if c.get('accepted') and encode(c['after']).strip()==guide.get('long_memory','').strip()),{})
  if first:
   f=fixture(r['source']);first=dict(first,diagnostic_expected=f['decisions'][first['event']]['expected_private'],optimizer_only=True)
  evidence.append(dict(case=r['case'],repeat=r['repeat'],status=r['status'],correct=r['correct'],planned=r['planned'],
       first_error=first,error_code=r.get('error_code'),
       update=change,guidance=guide,
       scope='development; citations and edits are model-produced evidence, not verified semantic truth'))
 for cap in (600,400,220,120):
  data=dict(parent=parent,evidence=[dict(r,update=clip(r['update'],cap),guidance=clip(r['guidance'],cap),excerpts_may_omit_evidence=True) for r in evidence],previous_effects=credits)
  try:
   _,_,audit=prepare(SYSTEM,data,SCHEMA)
   if audit['after_tokens']<8200:return data
  except ValueError:pass
 raise ValueError('delta_optimizer_evidence_too_large')

async def run(out,controller,budget,v19,v110):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 if (out/'report.json').exists():return read(out/'report.json')
 ledger=out/'learning-call-ledger.json'
 if not ledger.exists():
  old=read(Path(v110)/'learning/learning-call-ledger.json')
  # Explicit user authorization 2026-10-15: at most 4000 NEW learning calls.
  if old['limit']!=9745:raise RuntimeError('inherited_budget_limit_mismatch')
  dump(ledger,old)
  dump(out/'budget-extension.json',dict(previous=old,additional_new_calls=4000,authorized_by='user reply 2026-10-15: append at most4000; preserve cumulative ledger',new_limit=old['limit'],inherited_without_reset=True))
 LEARNING_LEDGER.set(ledger);current=copy.deepcopy(SEED);credits=[];promotions=0
 dump(out/'manifest.json',dict(version='delta-v2.0r1',cycles=2,sources_per_cycle=4,repetitions=2,
       new_parent_replays=True,parent_and_candidate_same_delta_architecture=True,formal48_not_read=True,
       no_native_fixed_baseline_reruns=True,engineering_seed_not_learned=True))
 for cycle in range(2):
  root=out/f'cycle-{cycle}';root.mkdir(exist_ok=True);done=read(root/'selection.json')
  if done:
   current=done['selected'];promotions+=int(done['effect']['accepted']);credits.append(done['effect']);continue
  fs=fixtures_from(v19,cycle);parent=compile_policy(current);dump(root/'parent-policy.json',parent)
  # Parent and candidate independently rebuild history; no false causal isolation claim.
  parent_rows=[]
  from trajectory_evolution import replay_case
  for f in fs:
   controller.state('delta_parent_replay',cycle=cycle,source=f['id'])
   rs=await asyncio.gather(*(replay_case(f,root/'parent-replays'/f"{f['id']}-r{rep}-parent",parent,budget,controller.wait_gateway) for rep in range(2)))
   parent_rows += [dict(r,case=f['id'],repeat=rep,policy='parent') for rep,r in enumerate(rs)]
   dump(root/'parent-rows.json',parent_rows)
  controller.state('delta_feedback_learning',cycle=cycle)
  data=packet(current,root/'parent-replays',parent_rows,credits);dump(root/'feedback-packet.json',data)
  proposed=await cached_structured(root/'proposal',SYSTEM,data,SCHEMA,controller.wait_gateway)
  candidate=compile_policy(proposed);screen_generic(candidate)
  critic=await cached_structured(root/'critic','Check generic memory-management rules: no concrete task answers, no benchmark identities, no mandatory finish/continuation override; preserve user authority.',proposed,CRITIC,controller.wait_gateway)
  chosen=current;effect=dict(accepted=False,reason='critic_or_unchanged')
  if all(critic[k] for k in ('generic','no_task_answers','preserves_user_authority')) and candidate!=parent:
   dump(root/'candidate-policy.json',candidate);rows=list(parent_rows)
   for f in fs:
    controller.state('delta_candidate_replay',cycle=cycle,source=f['id'])
    rs=await asyncio.gather(*(replay_case(f,root/'candidate-replays'/f"{f['id']}-r{rep}-candidate",candidate,budget,controller.wait_gateway) for rep in range(2)))
    rows += [dict(r,case=f['id'],repeat=rep,policy='candidate') for rep,r in enumerate(rs)]
    dump(root/'paired-rows.json',rows)
   effect=select(rows,len(fs)*2)
   if effect['accepted']:chosen={k:proposed[k] for k in ('guidance','update')};promotions+=1
  dump(root/'selection.json',dict(selected=chosen,effect=effect));current=chosen;credits.append(effect)
 dump(out/'candidate-policy.json',compile_policy(current));dump(out/'candidate-procedures.json',current)
 report=dict(status='candidate_ready_for_test' if promotions else 'no_accepted_update',promotions=promotions,credits=credits,
       architecture_change_not_counted_as_rsi_gain=True)
 dump(out/'report.json',report);return report
