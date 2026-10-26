import pathlib,shutil,json,hashlib,sys,time,subprocess,os
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study';r=b/'study-scope-v2';src=b/'v2-incoming'
assert not r.exists(),'Preserve existing V2 results'
r.mkdir()
for name in ('code','source'):shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to(old/'paos-core',target_is_directory=True)
for name in ('orders.json','budget.json','parent-policy.json','allocation.json'):
 shutil.copy2((b if name=='allocation.json' else old)/name,r/name)
for name in ('method.py','case_v2.py','queue_v2.py'):shutil.copy2(src/name,r/'code'/name)
for p in list((r/'code').rglob('*.py'))+list((r/'source').glob('*.py')):p.write_text(p.read_text().replace(str(old),str(r)))
# Clarify the public API uniformly for native and every ablation; no state/answer injection.
p=r/'source/action_catalog.py';s=p.read_text().replace("'scope': 'the currently issued kitchen work order',","'scope': 'one explicitly issued, not-yet-completed kitchen work order; excludes table service',\n        'precondition': 'The public user issued this particular work order and no correlated receipt has completed it. A table priority list or Continue does not issue a kitchen work order.',")
s=s.replace("'no object-specific action name or A-G table mapping is required'","'table service uses the separate table-scoped catalog entry, never this skill'")
p.write_text(s)
sys.path.insert(0,str(r/'code'));import method
parent=json.loads((r/'parent-policy.json').read_text());parent['guidance']=method.guidance_rule(method.GUIDANCE_PARENT);(r/'parent-policy.json').write_text(json.dumps(parent,indent=2)+'\n')
for name in ('policies','jobs','logs'):(r/name).mkdir()
arms=['gu_parent','native','g_only','u_only','think_u']
for arm in arms:(r/'policies'/f'{arm}.json').write_text(json.dumps(method.policy_for(parent,None,arm),indent=2)+'\n')
m=json.loads((old/'registration.json').read_text());allocation=json.loads((r/'allocation.json').read_text());node=allocation['node']
conditions=[c for c in m['training_conditions'] if c['condition_id'] in allocation['allowed_condition_ids']]
preferred='hEDABC-v1-i0' if node=='107' else 'hEADCB-v1-i1';conditions.sort(key=lambda c:c['condition_id']!=preferred)
schedule=[]
for i,c in enumerate(conditions):
 shift=(i+(0 if node=='107' else 1))%len(arms)
 for arm in arms[shift:]+arms[:shift]:schedule.append(dict(c,arm=arm,output=str(r/'development'/c['condition_id']/arm)))
(r/'development-schedule.json').write_text(json.dumps(schedule,indent=2)+'\n')
m['registered_at']=time.time();m['deployment_backend']={'policy':'verified original CUDA/JAX pi05_libero on original server GPU '+('6' if node=='107' else '7'),'physics':'LIBERO software EGL on node '+node,'policy_port':20517,'development_only':True}
m['administrative_amendments'].append({'reason':'User requested reuse of historically qualified physical implementation and correction of G scope mapping','manual_parent_revision':True,'not_RSI_result':True,'prior_results':str(old),'fair_budget_all_arms':True,'no_heldout_inputs_used':True})
for name in list(m['frozen_files']):m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
for p in [r/'code/case_v2.py',r/'code/queue_v2.py',r/'source/action_catalog.py',r/'development-schedule.json',r/'allocation.json']:
 m['frozen_files'][str(p.relative_to(r))]=hashlib.sha256(p.read_bytes()).hexdigest()
(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n');(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
(r/'env.sh').write_text((b/'env.sh').read_text().replace(str(old),str(r)))
print(json.dumps({'root':str(r),'node':node,'jobs':len(schedule),'first':schedule[0]}))
