import pathlib,json,shutil,hashlib,time,sys,os,signal,subprocess
b=pathlib.Path('/data/songziying/paos-libero-20261023');old=b/'study-scope-v2';r=b/'study-scope-v3';state=json.loads((old/'queue-status.json').read_text());pid=state['pid']
assert not r.exists()
assert state['phase']=='running'
cmd=pathlib.Path(f'/proc/{pid}/cmdline').read_bytes();assert str(old/'code/queue_v2.py').encode() in cmd
# Pause only the queue dispatcher. Its already-running case continues normally.
os.kill(pid,signal.SIGSTOP)
r.mkdir()
for name in ('code','source','policies'):shutil.copytree(old/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to(old/'paos-core',target_is_directory=True)
for name in ('orders.json','budget.json','parent-policy.json','allocation.json','development-schedule.json','env.sh'):shutil.copy2(old/name,r/name)
for p in list((r/'code').rglob('*.py'))+list((r/'source').glob('*.py')):p.write_text(p.read_text().replace(str(old),str(r)))
shutil.copy2(b/'v3-incoming/method.py',r/'code/method.py')
# Shared runtime budget, for native, G, U, GU and equal-call control alike.
p=r/'source/model_provider.py';s=p.read_text();assert 'OUTPUT_CAP = 2048' in s;s=s.replace('OUTPUT_CAP = 2048','OUTPUT_CAP = 8192');p.write_text(s)
p=r/'source/runtime_config.py';p.write_text(p.read_text().replace('OUTPUT_CAP = 2048','OUTPUT_CAP = 8192'))
p=r/'budget.json';d=json.loads(p.read_text());d['output_tokens']=8192;p.write_text(json.dumps(d,indent=2)+'\n')
for name in ('development-schedule.json','env.sh'):
 p=r/name;p.write_text(p.read_text().replace(str(old),str(r)))
for name in ('jobs','logs'):(r/name).mkdir()
m=json.loads((old/'registration.json').read_text());m['registered_at']=time.time();m['output_token_limit']=8192;m['administrative_amendments'].append({'reason':'Observed G report_advice truncation at 2048 tokens in development; shared 8192 output cap and concise advisor format for G and equal-call control','old_root':str(old),'old_results_preserved':True,'same_budget_all_arms':True,'manual_revision_not_RSI':True,'time':time.time()})
for name in m['frozen_files']:m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
for name in ('source/model_provider.py','source/runtime_config.py'):m['frozen_files'][name]=hashlib.sha256((r/name).read_bytes()).hexdigest()
(r/'registration.json').write_text(json.dumps(m,indent=2)+'\n');(r/'registration.sha256').write_text(hashlib.sha256((r/'registration.json').read_bytes()).hexdigest()+'\n')
(r/'handoff.json').write_text(json.dumps({'previous_queue_pid':pid,'previous_job':state['job'],'previous_root':str(old),'phase':'waiting_for_current_case','created':time.time()},indent=2))
with (r/'handoff.log').open('x') as log:
 p=subprocess.Popen([sys.executable,str(b/'v3-incoming/handoff.py'),str(r)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
(r/'handoff-pid.json').write_text(json.dumps({'pid':p.pid}));print(json.dumps({'root':str(r),'waiting_for':state['job'],'handoff_pid':p.pid}))
