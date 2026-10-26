from pathlib import Path
import ast,importlib.util,json,os,subprocess,time
R=Path('/data/stormlab/xi/robot');old=R/'paper-completion-20261020/gpu1-7-routing-20261021';new=R/'paper-completion-20261020/gpu5-after-remem-20261021';new.mkdir(exist_ok=True);src=(old/'worker-routing.py').read_text();assert src.count("NEW='choices=[1,2,3,4,7]'")==1;src=src.replace("NEW='choices=[1,2,3,4,7]'","NEW='choices=[1,2,3,4,5,7]'");w=new/'worker-routing.py'
if w.exists():assert w.read_text()==src
else:w.write_text(src)
spec=importlib.util.spec_from_file_location('route',old/'relay.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r);cap=r.cap;out=r.OUT;r.verify()
raw=(r.ORIGINAL/'worker.py').read_text();modified=raw.replace('choices=[4,7]','choices=[1,2,3,4,5,7]',1);a=ast.parse(raw);b=ast.parse(modified);n=0
for node in ast.walk(b):
 if isinstance(node,ast.keyword) and node.arg=='choices' and isinstance(node.value,ast.List) and [getattr(x,'value',None) for x in node.value.elts]==[1,2,3,4,5,7]:node.value=ast.List(elts=[ast.Constant(4),ast.Constant(7)],ctx=ast.Load());n+=1
assert n==1 and ast.dump(a)==ast.dump(b)
bench=R/'runs/official-memory-adapter-v6-20261020/remem';co=cap.read(bench/'coordinator.json');assert co['pid']==827747 and not cap.alive(co);assert (bench/'study-complete.json').exists() and cap.read(bench/'adaptation-state.json')['phase']=='complete'
assert int(subprocess.check_output(['nvidia-smi','-i','5','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())<100,'gpu5_occupied'
runtime=cap.read(R/'runs/paper-completion-20261020/gpu56-priority/plan.json');env=runtime['component_env'];assert env['MEMRSI_OFFLINE_WAIT']=='1';test=subprocess.run([runtime['python'],str(w),'--help'],env=env,cwd=R,capture_output=True,text=True);assert test.returncode==0 and '{1,2,3,4,5,7}' in test.stdout,(test.returncode,test.stderr[-300:])
with cap.locked(out/'dispatch.lock'):
 assert not (out/'blocked.json').exists() and not (out/'launch-intent-gpu5.json').exists() and not (out/'worker-gpu5.json').exists()
 for k,v in cap.read(out/'claims.json',{}).items():assert (out/k/'result.json').exists() or cap.alive(v['identity']),'stale_claim'
 m=cap.read(out/'manifest.json');assert any(not (out/j['key']/'result.json').exists() for j in m['jobs'])
 audit=out/'gpu5-after-remem-20261021';audit.mkdir(exist_ok=True);cmd=[runtime['python'],str(w),'--gpu','5','--output',str(out)]
 cap.write(audit/'authorization.json',dict(user_authorization='All GPU1-7 allowed; GPU0 reserved. ReMem formally complete, no benchmark child remains.',remem_complete_sha256=cap.file_sha(bench/'study-complete.json'),old_coordinator=co,manifest_sha256=cap.file_sha(out/'manifest.json'),worker_sha256=cap.file_sha(w),tests=dict(ast_only_gpu_parser=True,real_runtime_help=True,zero_model_calls=True),methods_and_budgets_unchanged=True,time=time.time()))
 cap.write(out/'launch-intent-gpu5.json',dict(gpu=5,command=cmd,authorization=str(audit/'authorization.json'),time=time.time()))
 with (out/'worker-gpu5.log').open('ab') as f:p=subprocess.Popen(cmd,cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
 who=cap.identity(p.pid);launched=cap.read(out/'launched.json');launched['workers']['5']=who;cap.write(out/'launched.json',launched);cap.write(audit/'launched.json',dict(identity=who,time=time.time(),next_relay_tracks_all_launched_workers=True));print(json.dumps({'gpu5':who,'tests':'AST equivalence and real CLI --help; no model calls'}))
