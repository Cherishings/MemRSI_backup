"""One-time audited launch for explicit user GPU authorization."""
import ast,hashlib,importlib.util,json,os,signal,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('relay',HERE/'relay.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
cap=r.cap;out=r.OUT;audit=r.AUDIT
spec=importlib.util.spec_from_file_location('routing',HERE/'worker-routing.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)

def main():
    raw=w.ORIGINAL.read_text();modified=w.routed_source(raw)
    # Only the GPU parser choices may differ. Actual locks/claims/trials are identical.
    before=ast.parse(raw);after=ast.parse(modified)
    diffs=0
    for node in ast.walk(after):
        if isinstance(node,ast.keyword) and node.arg=='choices' and isinstance(node.value,ast.List) and [getattr(e,'value',None) for e in node.value.elts]==[1,2,3,4,7]:
            node.value=ast.List(elts=[ast.Constant(value=4),ast.Constant(value=7)],ctx=ast.Load());diffs+=1
    assert diffs==1 and ast.dump(before)==ast.dump(after)
    # Execute only the original parser statements, stopping before any engine work.
    main_node=next(n for n in ast.parse(modified).body if isinstance(n,ast.FunctionDef) and n.name=='main')
    import argparse,contextlib,io,sys
    cli=ast.Module(body=main_node.body[:6],type_ignores=[])
    # Exact source prefix contains parser creation, add arguments, parse and out path.
    parser_code=modified.split('def main():\n',1)[1].split('\n spec=',1)[0]
    parser_code='\n'.join(line[1:] for line in parser_code.splitlines())
    for gpu in range(8):
        ns={'argparse':argparse,'Path':Path};old=sys.argv;sys.argv=['worker','--gpu',str(gpu),'--output','/tmp/routing-test-no-execution']
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                try:exec(parser_code,ns);ok=True
                except SystemExit:ok=False
        finally:sys.argv=old
        assert ok==(gpu in [1,2,3,4,7])
    runtime=cap.read(r.ROOT/'runs/paper-completion-20261020/gpu56-priority/plan.json')
    result=subprocess.run([runtime['python'],str(HERE/'worker-routing.py'),'--help'],env=runtime['component_env'],cwd=r.ROOT,capture_output=True,text=True)
    assert result.returncode==0,(result.returncode,result.stderr[-1000:])
    assert '{1,2,3,4,7}' in result.stdout
    assert not audit.exists(),'existing_authorization_requires_audit'
    assert not (out/'claims.json').exists() and not list(out.glob('launch-intent-gpu*.json')) and not (out/'blocked.json').exists()
    plan=cap.read(out/'relay-plan.json');old={'pid':1008756,'start_ticks':'368600492'}
    assert cap.alive(old) and cap.identity(old['pid'])==old
    assert Path(f'/proc/{old["pid"]}').stat().st_uid==os.getuid()
    assert b'guidance-diagnostic-20261021/schedule.py' in Path(f'/proc/{old["pid"]}/cmdline').read_bytes()
    assert cap.read(out/'relay-progress.json')['phase']=='waiting_predecessor'
    assert not Path(f'/proc/{old["pid"]}/task/{old["pid"]}/children').read_text().strip()
    for gpu in [1,2,3]:
        used=int(subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
        assert used<100,f'gpu{gpu}_occupied'
    authorization={'time':time.time(),'user_instruction':'有空卡了，除了0之外所有的卡都可以用了，帮我加快进度，谢谢','allowed_gpu':[1,2,3,4,5,6,7],'reserved_gpu':[0],'benchmark_priority':[5,6],'diagnostic_now':[1,2,3],'diagnostic_after_predecessor':[4,7],'registered_manifest_sha256':cap.file_sha(out/'manifest.json'),'original_relay_plan':plan,'old_scheduler':old,'routing_code_sha256':{n:cap.file_sha(HERE/n) for n in ['worker-routing.py','relay.py']},'zero_model_tests':{'ast_only_gpu_choices':True,'gpu_parser_cases':8,'real_runtime_help':True},'entry_dependency_fix':'add registered core to sys.path before cap10_ops import; memory_policy hash verified; initial --help failure had zero calls/claims/attempts','method_scoring_budget_attempts_unchanged':True}
    cap.write(audit/'authorization.json',authorization)
    for name in ['relay-plan.json','relay-progress.json','scheduler.json','scheduler-launch.json']:
        if (out/name).exists():cap.write(audit/('old-'+name),cap.read(out/name))
    os.kill(old['pid'],signal.SIGTERM)
    for _ in range(50):
        if not cap.alive(old):break
        time.sleep(.1)
    assert not cap.alive(old),'old_scheduler_not_retired'
    cap.write(audit/'retired-scheduler.json',{'identity':old,'time':time.time(),'reason':'user_resource_release_only_no_child_cases_interrupted'})
    me=cap.identity()
    with cap.locked(out/'scheduler.lock',nonblocking=True):
        workers={str(g):r.launch(g,me) for g in (1,2,3)}
    with (audit/'relay.log').open('ab') as log:
        cap.write(audit/'relay-launch-intent.json',{'time':time.time(),'command':['python3',str(HERE/'relay.py')]})
        proc=subprocess.Popen(['python3',str(HERE/'relay.py')],cwd=r.ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    relay=cap.identity(proc.pid)
    cap.write(audit/'launched.json',{'time':time.time(),'workers':workers,'relay':relay})
    print(json.dumps({'workers':workers,'relay':relay,'tests':'AST equivalence, 8 GPU CLI cases and real runtime help; zero model calls'}))
if __name__=='__main__':main()
