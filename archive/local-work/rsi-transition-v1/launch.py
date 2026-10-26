"""One registered transition-feedback run; preflight is zero-model and fails closed."""
import pathlib,json,shutil,hashlib,os,sys,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023')
old=b/'study-rsi-typed-process-v1';template=b/'study-rsi-process-edit-v1';r=b/'study-rsi-transition-v1';incoming=b/'rsi-transition-v1-incoming'
assert not r.exists(),'Do not duplicate registered version'
state=json.loads((b/'active-learning.json').read_text());assert state['root']==str(old)
assert not pathlib.Path('/proc/'+str(state['pid'])).exists(),'Previous learner still present'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
sys.path[:0]=[str(incoming),str(template/'code'),str(template/'source')]
import learn
from transitions import build
from paired import build_view
from request_view import line_pack
from runtime_contract import extract
from anchor_catalog import schema_for
from token_accounting import request_tokens
parent=read(template/'parent-policy.json');req=read(incoming/'full-request.json');data=json.loads(req['messages'][1]['content'])
evidence=build(old)
assert evidence==read(incoming/'training-transitions.json'),'Training extraction changed'
assert data['training_archive_transitions']==json.loads(json.dumps(line_pack(build_view(evidence)))),'Prepared evidence differs from training-only reconstruction'
assert data['parent']==learn.procedures(parent)
assert req['tools'][0]['function']['parameters']==schema_for(learn.procedures(parent),learn.JOINT_SCHEMA)
assert request_tokens(req['messages'],req['tools'])==49016
assert sha(incoming/'governance.py')==sha(template/'code/governance.py')
assert sha(incoming/'method.py')==sha(template/'code/method.py')
# Only saved training candidates and proposal artifacts, never validation or physical trajectories.
hashes={learn.digest(parent)};provenance=[];excluded=[]
for study in sorted(b.glob('study-rsi-*')):
 for p in sorted((study/'learning/policies').glob('*.json')):
  value=read(p)
  try:learn.procedures(value)
  except (ValueError,KeyError,TypeError):continue
  h=learn.digest(value);hashes.add(h);provenance.append({'path':str(p),'file_sha256':sha(p),'canonical':h})
 for p in sorted((study/'learning/proposals').glob('*/value.json')):
  value=read(p)
  if 'guidance_replacement' not in value:continue
  try:h=learn.digest(learn.joint_combinations(parent,value)['joint'])
  except (ValueError,KeyError,TypeError) as e:
   excluded.append({'path':str(p),'file_sha256':sha(p),'reason':str(e)});continue
  hashes.add(h);provenance.append({'path':str(p),'file_sha256':sha(p),'canonical':h})
assert '16c674f098206ebae95df13ca1a578dd988e8ee47555a6d028d259f923e93bb1' in hashes
ledger=read(old/'learning/learning-call-ledger.json');assert ledger=={'calls':3992,'limit':24000},ledger
r.mkdir()
for name in ['code','source']:shutil.copytree(template/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to((template/'paos-core').resolve(),target_is_directory=True)
for name in ['parent-policy.json','budget.json','training-sources.json']:shutil.copy2(template/name,r/name)
(r/'validation-sources.json').write_text('[]\n')
for name in ['learn.py','prepared.py']:shutil.copy2(incoming/name,r/'code'/name)
for name in ['full-request.json','training-transitions.json','request-budget-audit.json']:shutil.copy2(incoming/name,r/name)
(r/'candidate-denylist.json').write_text(json.dumps({'joint_sha256':sorted(hashes),'sources':provenance,'invalid_proposals_preserved_excluded':excluded},indent=2))
(r/'prepared-registration.json').write_text(json.dumps({'request_sha256':sha(r/'full-request.json'),'denylist_sha256':sha(r/'candidate-denylist.json'),'input_tokens':49016}))
from prepared import load
load(r,learn.procedures(parent),schema_for(learn.procedures(parent),learn.JOINT_SCHEMA),extract(r/'code/method.py'),request_tokens)
reg={'registered_at':time.time(),'version':'joint-transition-v1','node':'107','previous_root':str(old),'primary_method':'joint',
'changes':['Exact preassembled training transition evidence replaces older optimizer evidence; runtime and critic unchanged','All 32 training summaries, eight four-arm common-event archive comparisons, explicitly attributed known erroneous transition','Exact whole-line memory references; geometry omission explicitly recorded; model comprehension not validated'],
'proposal_limit':1,'critic_limit':1,'training_replays_max':32,'repetitions':2,'source_limit':4,'call_limit':24000,'carried_calls':3992,
'validation_accessed':False,'test_accessed':False,'physical_feedback_in_optimizer':False,'automatic_resampling':False,
'offline_tests_passed':70,'offline_test_notes':'50 controller and 20 evidence tests. Initial missing network_wait dependency fixed via test PYTHONPATH; later live health probe in legacy mock test replaced with mocked probe after wait. No model calls in tests. First launch preflight rejected tuple-versus-JSON-list comparison before root creation; canonical JSON comparison fixed without altering request.',
'input_audit_units':49016,'input_limit':49152,'input_note':'Frozen o200k accounting, exact messages/tools; not a gateway tokenizer assertion',
'candidate_denylist_entries':len(hashes),'previous_report_sha256':sha(old/'learning/report.json'),
'files':{str(p.relative_to(r)):sha(p) for folder in ['code','source'] for p in (r/folder).rglob('*.py')},
'inputs':{name:sha(r/name) for name in ['full-request.json','training-transitions.json','prepared-registration.json','candidate-denylist.json','parent-policy.json','budget.json','training-sources.json']}}
(r/'controller-registration.json').write_text(json.dumps(reg,indent=2))
(r/'learning').mkdir();(r/'learning/learning-call-ledger.json').write_text(json.dumps(ledger))
(r/'learning/carried-costs.json').write_text(json.dumps({'from':str(old),'previous_calls':3992,'raw_cost_logs_retained_at':str(old/'learning'),'include_transitive_carried_costs':True,'additional_physical_cost_roots':[str(b/n) for n in ['study-contract-validation-v1','study-contract-feasible-pilot-v1','study-feedback-v2-physical-pilot']],'physical_costs_separate_from_learner_ledger':True}))
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
args=[sys.executable,str(r/'code/learn.py'),'--root',str(r),'--source',str(r/'source'),'--core',str(r/'paos-core'),'--train-manifest',str(r/'training-sources.json'),'--validation-manifest',str(r/'validation-sources.json'),'--parent-policy',str(r/'parent-policy.json'),'--budget',str(r/'budget.json')]
with (r/'controller.log').open('x') as log:p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
state={'root':str(r),'pid':p.pid,'time':time.time(),'phase':'joint_paired_transition_training_only','node':'107'}
(r/'controller-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
