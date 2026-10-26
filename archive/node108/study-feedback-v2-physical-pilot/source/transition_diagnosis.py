"""Optimizer-only diagnosis of complete archive transitions; never actor hints.

Read the actual parent and previously rejected candidate. Compare information
before/after Update and before/after Guidance, preserving exact quoted witnesses.
These are model hypotheses, not causal proof or new runtime constraints.
"""
import copy
from pathlib import Path
from durable_queue import read
from replay import dump
from trajectory_replay import lines
from optimizer_context import prepare

FIELDS = {'target': 20, 'witness_a': 100, 'quote_a': 500,
          'witness_b': 100, 'quote_b': 500, 'finding': 1400}
DIAG_SCHEMA = dict(type='object', properties={k:dict(type='string',maxLength=v) for k,v in FIELDS.items()},
                   required=list(FIELDS), additionalProperties=False)
DIAG_SYSTEM = (
 'Diagnose memory information flow, not task performance alone. Supplied material is recorded development data. '
 'For archive transitions compare the COMPLETE before memory, received user instructions/execution feedback, and after memory. '
 'Omitted older history is unknown, not evidence of absence. Unrelated completion/cancellation does not authorize deleting other work. '
 'For a decision compare stored memory, selected exact evidence, current request, and actual choice. '
 'Return target update/guidance/actor/uncertain/control, two exact witness document IDs and verbatim quotes, and a finding. '
 'Use update only when received or previously retained requirements are lost, corrupted, or stale after archive; '
 'guidance when usable retained evidence is missed/distorted in selection; actor when supplied correct evidence is not used. '
 'Do not call remembered summaries authoritative merely because archived. Respect actual newer user updates and feedback. '
 'A successful control may use the same witness twice. Empty or missing documents cannot support an absence claim. '
 'Explain uncertainty. No repair proposal or answer-writing in this step. This diagnosis remains a hypothesis.'
)


def public_text(text):
    # Remove only the appended geometric observation; retain execution feedback.
    return str(text).split('Current scene')[0].strip()


def pick_row(rows):
    # source_error_corrected is a successful bounded suffix, NOT a failure.
    return min(rows, key=lambda r:(0 if any(not d['correct'] for d in r.get('decisions',[])) else
                                  1 if r.get('error_code') else 2, r['repeat']))


def evidence_units(f, row, root, arm='parent'):
    dest=Path(root)/f"{row['case']}-r{row['repeat']}-{arm}"/f"attempt-{row['attempts']:02d}"
    wrong=next((d for d in row.get('decisions',[]) if not d['correct']),None)
    last=wrong['event'] if wrong else max((d['event'] for d in row.get('decisions',[])), default=min(f['targets']))
    # A failure in archive after the final answered event is part of the trace.
    if row.get('failure_phase')=='archive':last+=1
    archives=[]
    for p in dest.glob('rollover-*/audit.json'):
        audit=read(p)
        if audit['last_received_event']<=last:
            archives.append((audit['last_received_event'],p.parent,audit))
    units=[]
    for event,p,audit in sorted(archives):
        prefix=f'archive-{event}'
        docs={prefix+'-before':(p/'memory-before.md').read_text(),
              prefix+'-after':(p/'memory-after.md').read_text() if (p/'memory-after.md').exists() else '[No archive output recorded]',
              prefix+'-received':'\n'.join(public_text(m['content']) for m in read(p/'messages-before.json',[])
                                          if m['role']=='user')}
        units.append(dict(kind='archive',event=event,success=audit.get('success'),documents=docs))
    guides=lines(dest/'guidance-events.jsonl')
    guide=next((g for g in guides if g.get('current_request','').startswith(f'Event {last}:')),None)
    if guide:
        import json
        docs={'decision-memory':guide.get('long_memory',''),
              'decision-selected':json.dumps(guide.get('generated',{}),ensure_ascii=False),
              'decision-request':public_text(guide.get('current_request','')),
              'decision-observed':json.dumps(wrong or next((d for d in reversed(row.get('decisions',[])) if d['event']==last),{}))}
        if wrong:docs['decision-private-scoring']=str(f['decisions'][last]['expected_private'])
        units.append(dict(kind='decision',event=last,documents=docs))
    if not units:raise RuntimeError('missing_actual_transition_evidence')
    return units


def pack_units(units, metadata):
    """Complete units only, never head/tail-clipped archives. Bounded request size."""
    batches=[];batch=[]
    def fits(values):
        data=dict(metadata,units=values,documents={k:v for u in values for k,v in u['documents'].items()})
        # Do not duplicate complete documents in the payload.
        data['units']=[{k:v for k,v in u.items() if k!='documents'} for u in values]
        try:
            _,_,audit=prepare(DIAG_SYSTEM,data,DIAG_SCHEMA)
            return audit['before_tokens']<=8800,data
        except ValueError:return False,data
    for unit in units:
        ok,data=fits(batch+[unit])
        if not ok:
            if not batch:raise RuntimeError('single_transition_exceeds_optimizer_budget')
            batches.append(fits(batch)[1]);batch=[]
            ok,data=fits([unit])
            if not ok:raise RuntimeError('single_transition_exceeds_optimizer_budget')
        batch.append(unit)
    if batch:batches.append(fits(batch)[1])
    return batches


def validate_diagnosis(value, docs):
    if value['target'] not in ('update','guidance','actor','uncertain','control'):
        raise ValueError('invalid_diagnostic_target')
    for suffix in ('a','b'):
        key=value['witness_'+suffix];quote=value['quote_'+suffix]
        if key not in docs or not quote.strip() or quote not in docs[key]:
            raise ValueError('unsupported_diagnostic_quote')
    return value


async def diagnose(f,row,root,out,request,wait_gateway,arm='parent'):
    meta=dict(case=row['case'],repeat=row['repeat'],arm=arm,status=row['status'],error_code=row.get('error_code'),
              evidence_scope='complete individual transitions; earlier unshown history unknown; development only')
    units=evidence_units(f,row,root,arm)
    batches=pack_units(units,meta);results=[]
    for i,data in enumerate(batches):
        path=Path(out)/f'window-{i:02d}'
        dump(path/'evidence.json',data)
        value,rejected=await request(path/'diagnosis',DIAG_SYSTEM,data,DIAG_SCHEMA,wait_gateway)
        if value:
            try:validate_diagnosis(value,data['documents'])
            except ValueError as ex:rejected={'code':str(ex)};value=None
        item=dict(window=i,diagnosis=value,rejection=rejected)
        dump(path/'verified.json',item);results.append(item)
    dump(Path(out)/'report.json',dict(**meta,windows=len(batches),transitions=len(units),results=results))
    return results


def prior_contrasts(root):
    root=Path(root);rows=read(root/'paired-rows.json',[]);groups={}
    for r in rows:groups.setdefault((r['case'],r['repeat']),{})[r['policy']]=r
    differences=[]
    for key,g in sorted(groups.items()):
        if set(g)!={'parent','candidate'}:raise RuntimeError('incomplete_old_pair')
        differences.append(dict(case=key[0],repeat=key[1],correct_delta=g['candidate']['correct']-g['parent']['correct'],
            parent_status=g['parent']['status'],candidate_status=g['candidate']['status']))
    return dict(prior_candidate=read(root/'candidate-policy.json'),all_pair_differences=differences,
                previous_effect=read(root/'selection.json')['effect'],
                warning='Rejected earlier edit: improvements and regressions both retained; not a new success claim')


async def diagnosed_packet(parent,fs,rows,root,out,credits,old_cycle,request,wait_gateway):
    findings=[]
    for f in fs:
        row=pick_row([r for r in rows if r['case']==f['id']])
        result=await diagnose(f,row,root,Path(out)/f['id'],request,wait_gateway)
        findings.append(dict(case=f['id'],status=row['status'],repeat=row['repeat'],windows=result))
    contrast=prior_contrasts(old_cycle)
    # All earlier regressions are reported; diagnose the first one per case, at
    # most two cases per cycle, selected by stable ID (not by apparent repairability).
    old_rows=read(Path(old_cycle)/'paired-rows.json');seen=set()
    for diff in contrast['all_pair_differences']:
        if diff['correct_delta']>=0 or diff['case'] in seen:continue
        seen.add(diff['case'])
        f=next(f for f in fs if f['id']==diff['case'])
        row=next(r for r in old_rows if r['case']==diff['case'] and r['repeat']==diff['repeat'] and r['policy']=='candidate')
        # Last decision plus preceding archive: targeted regression control, all
        # old parent transitions remain covered above.
        units=evidence_units(f,row,Path(old_cycle)/'candidate-replays','candidate')[-2:]
        for i,data in enumerate(pack_units(units,dict(case=f['id'],role='previous_rejected_candidate_regression'))):
            path=Path(out)/('regression-'+f['id'])/f'window-{i:02d}';dump(path/'evidence.json',data)
            val,rej=await request(path/'diagnosis',DIAG_SYSTEM,data,DIAG_SCHEMA,wait_gateway)
            if val:
                try:validate_diagnosis(val,data['documents'])
                except ValueError as ex:rej={'code':str(ex)};val=None
            findings.append(dict(case=f['id'],role='old_regression',windows=[dict(diagnosis=val,rejection=rej)]))
        if len(seen)==2:break
    # Select the earliest supported Update witness and latest selection witness
    # per trace; retain counts and all unselected diagnosis artifacts on disk.
    packed=[]
    for trace in findings:
        vals=[x['diagnosis'] for x in trace['windows'] if x.get('diagnosis')]
        selected=[]
        for target in ('update','guidance','actor','control','uncertain'):
            items=[v for v in vals if v['target']==target]
            if items:selected.append(items[-1] if target=='guidance' else items[0])
        packed.append({**{k:v for k,v in trace.items() if k!='windows'},'diagnoses':selected,
                       'all_window_count':len(trace['windows']),'valid_diagnosis_count':len(vals)})
    data=dict(parent=parent,transition_diagnoses=packed,previous_rejected_edit=contrast,previous_effects=credits,
              runtime_interface='unchanged original compact store, save_memory, exact fragment-ID Guidance',
              rule_character_limit=1600,diagnosis_is_hypothesis=True)
    dump(Path(out)/'full-proposal-packet.json',data)
    # If needed remove whole redundant diagnostic categories, never clip quotes.
    for targets,maximum in ((None,5),(('update','guidance','actor'),2),(('update','guidance','actor'),1)):
        value=copy.deepcopy(data)
        if targets:
            for trace in value['transition_diagnoses']:
                trace['diagnoses']=[d for d in trace['diagnoses'] if d['target'] in targets][:maximum]
        try:
            _,_,audit=prepare('x '*900,value,{'type':'object','properties':{},'required':[]})
            if audit['before_tokens']<8000:return value
        except ValueError:pass
    raise RuntimeError('diagnostic_packet_cannot_fit_without_clipping')
