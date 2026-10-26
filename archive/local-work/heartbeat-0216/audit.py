import ast,copy,json,hashlib
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parent
source=(root/'frozen-method.py').read_text()
names={'public_messages','public_payload','advice_tools','validate_advice'}
tree=ast.parse(source);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
assert len(nodes)==4
ns={'copy':copy};exec(compile(ast.Module(body=nodes,type_ignores=[]),'frozen-interface-subset','exec'),ns)
request=json.loads((root/'critic-request.json').read_text());data=json.loads(request['messages'][1]['content'])
for n in nodes:
 if n.name!='public_messages':assert ast.get_source_segment(source,n)==data['existing_runtime_contract']['functions'][n.name]
payload=ns['public_payload']('memory placeholder','history placeholder',[{'role':'user','content':'message placeholder'}],'current placeholder','public action catalog placeholder')
evidence=payload['evidence'];schema=ns['advice_tools'](evidence)[0]['function']['parameters']
checks=[]
def check(name,value):
 assert value,name
 checks.append({'name':name,'passed':True})
check('existing_three_required_fields',set(schema['required'])=={'recommendation','basis_ids','uncertainty'} and schema['additionalProperties'] is False)
check('existing_top_level_dynamic_enum',schema['properties']['basis_ids']['items']['enum']==['memory','history','current','short:0'])
check('existing_max_five',schema['properties']['basis_ids']['maxItems']==5)
check('existing_word_guidance','under 80 words' in payload['output_contract'] and 'under 40 words' in payload['output_contract'])
def response(value):return SimpleNamespace(finish_reason='tool_calls',tool_calls=[SimpleNamespace(name='report_advice',arguments=value)])
value={'recommendation':'A generic nonbinding suggestion.','basis_ids':['current'],'uncertainty':''}
check('frozen_validator_accepts_source_key',ns['validate_advice'](response(value),evidence)==value)
try:ns['validate_advice'](response({**value,'basis_ids':['Event 44']}),evidence)
except ValueError as e:check('frozen_validator_rejects_event_label',str(e)=='guidance_advice_invalid_citation')
else:raise AssertionError('event label unexpectedly accepted')
check('empty_abstention_remains_valid',ns['validate_advice'](response({'recommendation':'','basis_ids':[],'uncertainty':''}),evidence)['recommendation']=='')
report=json.loads((root/'report.json').read_text());assert report['status']=='joint_proposal_rejected'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
out={'scope':'offline interface audit, synthetic placeholders, zero model calls, no validation or test traces','checks':checks,'source_sha256':sha(root/'frozen-method.py'),'critic_request_sha256':sha(root/'critic-request.json'),'original_report_sha256':sha(root/'report.json'),'critic_had_exact_frozen_functions':True,'finding':'Quoted fields, source-key restrictions, maximum items, and word guidance pre-existed in runtime. Rejection explanation conflicts with that supplied interface evidence. This audit does not grant acceptance or prove candidate efficacy.','original_rejection_preserved':True,'automatic_acceptance':False,'new_proposals':0,'new_critic_calls':0,'next_step':'Before any further optimizer run, design a bounded, preregistered critic calibration using synthetic interface-preserving and interface-changing controls; do not repeatedly review this candidate or alter criteria for a pass.'}
(root/'interface-audit.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'passed_checks':len(checks),'original_status':report['status'],'new_model_calls':0}))
