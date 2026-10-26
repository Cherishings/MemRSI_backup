"""Validate operative rule fields strictly; explanatory prose is optional.

Archived responses can be recovered without regenerating or editing a rule.
Only malformed new responses receive one bounded format resubmission.
"""
import copy,json
from pathlib import Path
from replay import dump
from evolution import PROPOSAL as OLD_PROPOSAL,CRITIC as OLD_CRITIC

PROPOSAL=copy.deepcopy(OLD_PROPOSAL)
PROPOSAL['required']=['update','guidance']
for key in PROPOSAL['required']:
    PROPOSAL['properties'][key].update(minLength=1,maxLength=1800)
CRITIC=copy.deepcopy(OLD_CRITIC)
CRITIC['required']=['generic','no_task_answers','preserves_user_authority']

class StructuredFailure(RuntimeError):pass

def parse_response(response,schema):
    # Accept both dataclass-asdict audit records and the provider's response.
    calls=response.get('tool_calls') or []
    if response.get('finish_reason') not in ('stop','tool_calls') or len(calls)!=1 or calls[0].get('name')!='submit':
        raise StructuredFailure('optimizer_protocol_failure')
    value=calls[0].get('arguments');properties=schema['properties']
    if not isinstance(value,dict) or not set(schema['required'])<=set(value) or set(value)-set(properties):
        raise StructuredFailure('optimizer_schema_failure')
    for key,item in value.items():
        rule=properties[key];kind=rule['type']
        if kind=='boolean' and type(item) is not bool:raise StructuredFailure('optimizer_field_type_failure')
        if kind=='string':
            if not isinstance(item,str):raise StructuredFailure('optimizer_field_type_failure')
            if (key in schema['required'] and not item.strip()) or len(item)>rule.get('maxLength',100000):
                raise StructuredFailure('optimizer_field_length_failure')
    return copy.deepcopy(value)

def recover_response(source,out,schema):
    source=Path(source);out=Path(out)
    # No cherry-picking among candidates or requests: the archived response must
    # be the only recorded response of this failed proposal invocation.
    rows=[json.loads(line) for line in (source/'model-trace.jsonl').read_text().splitlines()]
    if len(rows)!=1:raise StructuredFailure('ambiguous_archived_proposal')
    value=parse_response(rows[0]['response'],schema)
    out.mkdir(parents=True,exist_ok=False)
    dump(out/'value.json',value)
    dump(out/'recovery.json',{'source':str(source),'new_model_calls':0,'rule_text_unchanged':True,
         'optional_fields_absent':sorted(set(schema['properties'])-set(value))})
    return value

async def structured(out,system,data,schema):
    from dataclasses import asdict
    from model_provider import Provider
    out=Path(out);out.mkdir(parents=True,exist_ok=False);provider=Provider(out)
    from optimizer_context import prepare
    extra=[]
    try:
        for attempt in range(2):
            messages,tools,audit=prepare(system,data,schema,extra)
            dump(out/f'context-packing-{attempt}.json',audit)
            response=await provider.chat(messages=messages,tools=tools,tool_choice='required',model='gpt-5.6-luna')
            try:value=parse_response(asdict(response),schema)
            except StructuredFailure as error:
                dump(out/f'format-rejection-{attempt}.json',{'code':str(error),'format_resubmissions_remaining':1-attempt})
                if attempt:raise
                extra=[{'role':'user','content':json.dumps({
                    'format_notice':'The submission did not match the schema. Resubmit the same intended rules/analysis using the required fields. No task or feedback changed.',
                    'required_fields':schema['required'],'previous_submission':asdict(response)},ensure_ascii=False)}]
                continue
            dump(out/'value.json',value);return value
    finally:await provider._client.close()
