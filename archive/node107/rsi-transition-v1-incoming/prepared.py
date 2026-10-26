"""Read an immutable, training-only prepared proposal; never make model calls."""
import hashlib,json
from pathlib import Path

def load(root,parent,schema,runtime,count):
 root=Path(root);reg=json.loads((root/'prepared-registration.json').read_text())
 path=root/'full-request.json'
 if hashlib.sha256(path.read_bytes()).hexdigest()!=reg['request_sha256']:raise ValueError('prepared_request_hash')
 req=json.loads(path.read_text())
 if set(req)!={'messages','tools'}:raise ValueError('prepared_request_fields')
 messages=req['messages'];tools=req['tools']
 if len(messages)!=2 or [x['role'] for x in messages]!=['system','user']:raise ValueError('prepared_messages')
 data=json.loads(messages[1]['content'])
 if data['parent']!=parent:raise ValueError('prepared_parent')
 if {k:v for k,v in data['existing_runtime_contract'].items() if k!='source_path'}!={k:v for k,v in runtime.items() if k!='source_path'}:raise ValueError('prepared_runtime')
 if data['validation_feedback_provided'] is not False or data['test_feedback_provided'] is not False:raise ValueError('prepared_split')
 expected=[{'type':'function','function':{'name':'submit','description':'Submit one bounded result.','parameters':schema}}]
 if tools!=expected:raise ValueError('prepared_schema')
 tokens=count(messages,tools)
 if tokens!=reg['input_tokens'] or tokens>49152:raise ValueError('prepared_budget')
 deny=root/'candidate-denylist.json'
 if hashlib.sha256(deny.read_bytes()).hexdigest()!=reg['denylist_sha256']:raise ValueError('denylist_hash')
 hashes=json.loads(deny.read_text())['joint_sha256']
 if not hashes:raise ValueError('empty_denylist')
 return req,hashes,{'input_tokens':tokens,'input_limit':49152,'request_sha256':reg['request_sha256'],'exact_preassembled_request':True,'truncation_applied':False}

def reject_duplicate(proposed,hashes,digest):
 if digest(proposed['joint']) in hashes:raise ValueError('duplicate_previous_joint_candidate')
