"""Wider proposal text allowance; unchanged runtime rules/store/resource budget."""
import copy
import hashlib
import json
from pathlib import Path
from stream_design import compile_procedures
from feedback_learning import screen_generic
from structured_feedback import parse_response
from replay import dump

PATCH_SCHEMA = {'type':'object','properties':{
    'target':{'type':'string','enum':['guidance','update'],'maxLength':20},
    'anchor':{'type':'string','maxLength':450},
    'replacement':{'type':'string','maxLength':1200},
    'rationale':{'type':'string','maxLength':1200}},
    'required':['target','replacement','rationale'],'additionalProperties':False}


def apply_edit(parent, patch):
    parse_response(dict(finish_reason='tool_calls',tool_calls=[dict(name='submit',arguments=patch)]),PATCH_SCHEMA)
    target=patch['target']
    if target not in ('guidance','update'):raise ValueError('invalid_edit_target')
    old=parent[target];anchor=patch.get('anchor','')
    if len(anchor)>min(450,int(len(old)*.35)):raise ValueError('edit_not_local')
    if anchor and old.count(anchor)!=1:raise ValueError('anchor_not_unique')
    replacement=patch['replacement']
    new=old.replace(anchor,replacement,1) if anchor else old+'\n'+replacement
    if new.strip()==old.strip():raise ValueError('unchanged_edit')
    updated=copy.deepcopy(parent);updated[target]=new
    policy=compile_procedures(updated);screen_generic(policy)
    return updated,policy


def recover_last_submission(source, destination):
    """Revalidate the LAST already returned submission, never sample or edit it."""
    source=Path(source);destination=Path(destination)
    trace=source/'attempt-01/model-trace.jsonl'
    rejection=source/'attempt-01/format-rejection-1.json'
    if json.loads(rejection.read_text())['code']!='optimizer_field_length_failure':
        raise RuntimeError('unexpected_recovery_reason')
    records=[json.loads(line) for line in trace.read_text().splitlines()]
    if len(records)!=2:raise RuntimeError('unexpected_proposal_submission_count')
    value=parse_response(records[-1]['response'],PATCH_SCHEMA)
    destination.mkdir(parents=True,exist_ok=True)
    dump(destination/'value.json',value)
    dump(destination/'recovery.json',dict(source=str(source),trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),
        selected_submission='last',submission_count=len(records),new_model_calls=0,
        operative_text_unchanged=True,replacement_characters=len(value['replacement']),
        old_limit=450,new_limit=1200,final_operator_limit_unchanged=1600))
    return value
