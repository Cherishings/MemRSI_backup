import json,pathlib,hashlib,collections,time
root=pathlib.Path('/data/stormlab/xi/robot');base=root/'runs/paper-evolution-20261018';dest=root/'runs/paper-completion-20261020/archive-transport-repair';dest.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
rows=[];uncertain=[]
for study in sorted((base/'studies').iterdir()):
 if not study.is_dir():continue
 for result in sorted(study.glob('cycle-*/*-replays/*/result.json')):
  r=read(result)
  if r.get('error_code')!='native_session_archival_failed':continue
  attempts=sorted(result.parent.glob('attempt-*'))
  a=attempts[-1];audits=sorted(a.glob('rollover-*/audit.json'),key=lambda p:int(p.parent.name.split('-')[-1]))
  audit=read(audits[-1]);call=audit['model_calls'];errors=[]
  if (a/'model-errors.jsonl').exists():
   errors=[json.loads(x) for x in (a/'model-errors.jsonl').read_text().splitlines()]
  matches=[e for e in errors if e.get('call')==call]
  e=matches[-1] if matches else None
  item=dict(run_id=study.name,replay=str(result.parent),relative=str(result.parent.relative_to(study)),original_result_sha256=sha(result),policy_sha256=sha(a/'policy.json'),source=r['source'],old_attempt_count=len(attempts),failed_archive_call=call,original_status=r['status'])
  if e and e.get('http_status') in (429,502,503,504) and audit.get('success') is False:
   item['provider_error']={k:e.get(k) for k in ['http_status','code','output_started','stage','retryable']};item['classification']='confirmed_transport_wrapped_by_archive';rows.append(item)
  else:item['classification']='archive_failure_without_same_call_transport_evidence';uncertain.append(item)
report=dict(schema=1,time_unix=time.time(),confirmed_transport=rows,not_reclassified=uncertain,counts=dict(collections.Counter(x['run_id'] for x in rows)),selection_valid_for_paper=False,reason='technical archive failures entered parent/candidate scores and cost gate',repair_scope='same frozen source, policy and repetition; only confirmed technical attempts; no valid success or capability replay rerun',max_attempts=3,global_limit=15000,per_run_limit=3000,old_artifacts_retained=True)
(dest/'audit.json').write_text(json.dumps(report,indent=2))
for study in sorted((base/'studies').iterdir()):
 if not study.is_dir():continue
 affected=[x for x in rows if x['run_id']==study.name]
 if affected:
  mark=dict(status='selection_quarantined_pending_transport_repair',audit=str(dest/'audit.json'),affected=len(affected),report_sha256=sha(study/'report.json'),original_report_retained=True,do_not_use_as_rsi_negative_or_positive=True)
  (study/'selection-integrity.json').write_text(json.dumps(mark,indent=2))
  ev=base/'evaluations'/study.name
  if ev.exists():(ev/'selection-integrity.json').write_text(json.dumps(mark,indent=2))
print(json.dumps({'confirmed':len(rows),'unreclassified':len(uncertain),'counts':report['counts'],'audit':str(dest/'audit.json')}))
