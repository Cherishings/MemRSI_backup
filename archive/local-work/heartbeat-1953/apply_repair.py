import pathlib,json,hashlib,os,sys,shutil,time,asyncio,subprocess
b=pathlib.Path('/data/songziying/paos-libero-20261023');r=b/'study-rsi-v4-learning-compact';a=r/'loader-repair-20261024';oldstate=json.loads((b/'active-learning.json').read_text())
assert oldstate['root']==str(r) and not pathlib.Path('/proc/'+str(oldstate['pid'])).exists()
assert not a.exists(),'Repair already registered; inspect instead of repeat'
l=r/'learning';fail=l/'training/replays/001-g_only_edit-r0';fr=json.loads((fail/'result.json').read_text());assert fr['failure_phase']=='initializing' and fr['logical_calls']==0 and fr['status']=='unclassified_failure'
assert not (l/'validation').exists() and not (l/'report.json').exists()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
identities={str(p.relative_to(r)):sha(p) for p in (l/'policies').glob('*.json')};parent_result=l/'training/replays/000-parent-r0/result.json';parent_hash=sha(parent_result)
ledger=json.loads((l/'learning-call-ledger.json').read_text());assert ledger['calls']==22
# Preserve every old file before changing compatibility checks.
a.mkdir();changes={}
for name in ['memory_policy','memory_design']:
 dst=r/'source'/f'{name}.py';src=b/'rsi-v4-incoming'/f'{name}-loaderfix.py';shutil.copy2(dst,a/dst.name);changes[str(dst.relative_to(r))]={'before':sha(dst),'after':sha(src)};shutil.copy2(src,dst)
reg={'registered_at':time.time(),'classification':'runtime_loader_contract_mismatch','symptom':fr,'root_cause':'learner body bound4096 vs legacy serialized field bound1800 and U body bound1600','changes':changes,'candidate_policy_hashes_unchanged':identities,'parent_completed_result_sha256':parent_hash,'old_failure_preserved_at':str(a/'failed-initialization'),'technical_replacement_maximum':1,'new_proposals':0,'method_scoring_budgets_changed':False,'ledger_before':ledger,'validation_feedback_used':False,'physical_tests_started':False,'phase':'patched_preflight_pending'}
(a/'repair.json').write_text(json.dumps(reg,indent=2))
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')]
os.environ['PAOS_LIBERO_SOURCE']=str(r/'source');os.environ['PAOS_CORE_ROOT']=str(r/'paos-core')
import learn,method
module=learn.install_runtime(str(r/'source'),str(r/'paos-core'))
async def forbidden_chat(*args,**kwargs):raise AssertionError('No API call permitted during constructor preflight')
module.Provider.chat=forbidden_chat
import twenty_agent,memory_policy,memory_design
async def preflight():
 for p in sorted((l/'policies').glob('*.json')):
  policy=json.loads(p.read_text());memory_policy.validate(policy);memory_design.update_instruction(policy['update'])
  cls=method.bind_agent_class(twenty_agent.TwentyAgent,'gu_parent',policy);agent=cls('memrsi',a/'constructors'/p.stem,p,r/'budget.json');assert agent.policy==policy;await agent.close()
asyncio.run(preflight())
assert json.loads((l/'learning-call-ledger.json').read_text())==ledger
assert all(sha(r/name)==h for name,h in identities.items()) and sha(parent_result)==parent_hash
# Move only the zero-model-call initialization failure into its permanent audit archive.
shutil.move(str(fail),str(a/'failed-initialization'))
for rel in ['learning/blocked.json','learning/training/blocked.json','learning/training/rows.json','learning/training/process-logs/001.log','controller.log']:
 p=r/rel;dst=a/'prior'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(p),str(dst))
reg.update(phase='preflight_passed_resume_registered',constructor_checks=4,model_calls_in_preflight=0);(a/'repair.json').write_text(json.dumps(reg,indent=2))
env=os.environ.copy();env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core')])
args=[sys.executable,str(r/'code/learn.py'),'--root',str(r),'--source',str(r/'source'),'--core',str(r/'paos-core'),'--train-manifest',str(r/'training-sources.json'),'--validation-manifest',str(r/'validation-sources.json'),'--parent-policy',str(r/'parent-policy.json'),'--budget',str(r/'budget.json')]
with (r/'controller.log').open('x') as log:proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
state={'root':str(r),'pid':proc.pid,'time':time.time(),'phase':'automatic_learning_resumed_after_loader_repair','node':'107','repair_registration':str(a/'repair.json')};(a/'resume-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
