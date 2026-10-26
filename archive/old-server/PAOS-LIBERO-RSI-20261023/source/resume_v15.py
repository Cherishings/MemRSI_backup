"""Recover only the last already returned design; never regenerate/select answers."""
import hashlib,json
from pathlib import Path
from replay import dump
from memory_design import MANDATORY,OPTIONAL,validate_design
from feedback_learning import aggregate

def project(response):
    calls=response.get('tool_calls') or []
    if response.get('finish_reason') not in ('tool_calls','stop') or len(calls)!=1 or calls[0].get('name')!='submit':
        raise ValueError('resume_response_protocol')
    value=calls[0].get('arguments')
    required={'fields','read_focus','retention_focus'}
    if not isinstance(value,dict) or not required<=set(value):raise ValueError('resume_missing_design')
    extras=set(value)-required
    if extras-set(MANDATORY+OPTIONAL) or any(not isinstance(value[k],str) for k in extras):
        raise ValueError('resume_unknown_extra')
    design={k:value[k] for k in ('fields','read_focus','retention_focus')}
    validate_design(design)
    return design,sorted(extras)

def restore(prior,out,fixtures):
    prior=Path(prior);out=Path(out)
    if json.loads((prior/'fixtures.json').read_text())!=fixtures:raise ValueError('resume_fixture_changed')
    if (prior/'round-1/decision.json').exists() or (prior/'report.json').exists():raise ValueError('resume_already_terminal')
    first=json.loads((prior/'round-0/decision.json').read_text())
    if first['decision']!='retain_parent_no_paired_gain':raise ValueError('resume_unexpected_parent')
    baseline=json.loads((prior/'seed-development/summary.json').read_text())
    if aggregate(baseline['rows'])!=baseline:raise ValueError('resume_baseline_changed')
    trace=prior/'round-1/proposal/model-trace.jsonl'
    responses=[json.loads(s)['response'] for s in trace.read_text().splitlines()]
    if len(responses)!=2:raise ValueError('resume_unexpected_attempt_count')
    design,extras=project(responses[-1])
    calls=sum(json.loads(p.read_text()).get('calls',0) for p in prior.rglob('calls.json'))
    dump(out/'resume.json',{'source':str(prior),'reused_development_evaluations':48,'prior_calls':calls,
          'resume_at_round':1,'new_proposal_calls':0,'format_attempts_already_used':2,
          'response_selection':'last returned response only, no score-based selection',
          'trace_sha256':hashlib.sha256(trace.read_bytes()).hexdigest(),
          'ignored_explanatory_keys':extras,'operative_fields_unchanged':True,
          'previous_failures_retained':True,'call_budget_not_reset':True})
    dump(out/'reused-round-0.json',first);dump(out/'reused-baseline.json',baseline)
    return baseline,first,design,calls
