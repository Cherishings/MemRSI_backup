"""Four declared episodes (two matched pairs); starts only with explicit approved shared-adapter path."""
import argparse,fcntl,hashlib,json,os,signal,subprocess,time
from pathlib import Path
from runtime import ROOT,ROBOT_ROOT,BASE,execution_env
from audit import code_hashes
POLICY=Path('/data/stormlab/xi/paos/results/memrsi-bounded-v2_2-20261015T175555Z/experiment/frozen-policy.json')

def identity(pid):return dict(pid=pid,start_ticks=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19])
def write(path,obj):
    q=path.with_suffix('.tmp');q.write_text(json.dumps(obj,indent=2));q.replace(path)
def hashes(folder):return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*.py'))}
def stop(child):
    if child and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--common',type=Path,required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--run-approved-pairs',action='store_true');p.add_argument('--entry-smoke',action='store_true');a=p.parse_args()
    if not (a.run_approved_pairs or a.entry_smoke):raise SystemExit('Review required: no paired test launched.')
    config=json.loads((ROOT/'protocol.json').read_text());assert a.gpu==3
    assert hashlib.sha256(POLICY.read_bytes()).hexdigest()==config['policy_hash']
    smoke=json.loads((ROBOT_ROOT/'runs/official-online-remem-r4-20261017/segment-check/result.json').read_text())
    assert smoke['status']=='pass' and smoke['history_preserved']
    assert smoke['source_hashes']==code_hashes(ROOT),'smoke_source_version_mismatch'
    initial=json.loads((ROBOT_ROOT/'runs/official-online-remem-r4-20261017/initial-state-check/result.json').read_text())
    assert initial['status']=='pass' and initial['source_hashes']==code_hashes(ROOT)
    if not a.entry_smoke:
        entry=ROBOT_ROOT/'runs/official-online-remem-r4-20261017/entry-smoke'
        assert json.loads((entry/'source-hashes.json').read_text())==code_hashes(ROOT)
        assert json.loads((entry/'common-hashes.json').read_text())==hashes(a.common)
        preflight_rows=json.loads((entry/'rows.json').read_text())
        assert len(preflight_rows)==2 and all(x['steps']>0 and x['answered_decisions']==1 and x['status'] not in ('agent_failure','technical_failure') for x in preflight_rows),'full_actor_entry_not_validated'
    assert (a.common/'visual_actor.py').exists() and (a.common/'visual-validation-ready.json').exists()
    a.output.mkdir(parents=True,exist_ok=True);frozen=hashes(a.common)
    manifest=[dict(seed=s,arm=arm) for s in ([config['preflight_seed']] if a.entry_smoke else config['seeds']) for arm in config['arms']]
    dependencies=json.loads((ROOT/'dependency-manifest.json').read_text())
    for name,expected in dependencies['overlay_hashes'].items():assert hashlib.sha256((ROOT/'actor-deps'/name).read_bytes()).hexdigest()==expected
    with (a.output/'queue.lock').open('a') as own:
        fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write(a.output/'identity.json',dict(**identity(os.getpid()),gpu=a.gpu,common=str(a.common)))
        for name,data in [('manifest.json',manifest),('common-hashes.json',frozen),('protocol.json',config),('source-hashes.json',code_hashes(ROOT))]:
            if (a.output/name).exists():assert json.loads((a.output/name).read_text())==data
            else:write(a.output/name,data)
        env=execution_env(a.gpu);actor_env=dict(env,PYTHONPATH=str(ROOT/'actor-deps')+':'+str(a.common/'deps')+':'+str(a.common)+':'+str(ROOT),LITELLM_LOCAL_MODEL_COST_MAP='True')
        rows=[]
        def stage(phase,**extra):write(a.output/'progress.json',dict(phase=phase,time=time.time(),**extra))
        for i,item in enumerate(manifest):
            assert hashes(a.common)==frozen;assert hashlib.sha256(POLICY.read_bytes()).hexdigest()==config['policy_hash']
            case=a.output/f'case-{i:03d}';case.mkdir(exist_ok=True)
            if (case/'result.json').exists():
                existing=json.loads((case/'result.json').read_text());rows.append(existing)
                if existing['status']=='technical_failure':stage('technical_failure_needs_diagnosis',index=i);return
                continue
            if (case/'started.json').exists():stage('interrupted_case_requires_audit',index=i);return
            controller=actor=None
            with Path(f'/data/stormlab/xi/paos/qwen-deploy/gpt-gpu{a.gpu}-run.lock').open('a') as gpu:
                while True:
                    try:
                        fcntl.flock(gpu,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        used=int(subprocess.check_output(['nvidia-smi','-i',str(a.gpu),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
                        if used<=1024:break
                        fcntl.flock(gpu,fcntl.LOCK_UN)
                    except BlockingIOError:pass
                    stage('waiting_gpu',index=i);time.sleep(15)
                prior=[] if a.entry_smoke else [x for x in config['previous_attempts'] if x['seed']==item['seed'] and x['arm']==item['arm']]
                attempt=len(prior)+1
                assert attempt<=config['per_case_attempt_limit']
                for old in prior:
                    old_result=json.loads((Path(old['path'])/'result.json').read_text())
                    assert old_result['status']=='technical_failure','capability_failure_retry_forbidden'
                write(case/'started.json',dict(**item,attempt=attempt,previous_attempts=prior,time=time.time()));(case/'controller').mkdir(exist_ok=True)
                try:
                    with (case/'controller.private.log').open('a') as log:
                        controller=subprocess.Popen([str(BASE/'venv/bin/robot'),str(ROOT/'controller_server.py'),'--seed',str(item['seed']),'--output',str(case/'controller')],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,pass_fds=(gpu.fileno(),))
                    stage('controller_starting',index=i,**item,controller=identity(controller.pid))
                    limit=time.monotonic()+240
                    while not (case/'controller/ready.json').exists():
                        if controller.poll() is not None:raise RuntimeError('controller_exited_before_ready')
                        if time.monotonic()>limit:raise TimeoutError('controller_initialization_timeout')
                        time.sleep(2)
                    if item['arm']=='memrsi':
                        native=a.output/f'case-{i-1:03d}'/'controller/initial-evidence.json'
                        previous=json.loads(native.read_text());current=json.loads((case/'controller/initial-evidence.json').read_text())
                        assert previous==current,'paired_initial_state_or_public_goal_mismatch'
                    with (case/'actor.private.log').open('a') as log:
                        actor=subprocess.Popen(['/home/xi/envs/agent/bin/python',str(ROOT/'pair_episode.py'),'--arm',item['arm'],'--seed',str(item['seed']),'--output',str(case),'--controller-output',str(case/'controller'),'--policy',str(POLICY),'--attempt',str(attempt)]+(['--entry-smoke'] if a.entry_smoke else []),env=actor_env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,pass_fds=(gpu.fileno(),))
                    stage('running',index=i,**item,controller=identity(controller.pid),actor=identity(actor.pid))
                    actor.wait()
                    if not (case/'result.json').exists():raise RuntimeError('actor_exit_without_result')
                    result=json.loads((case/'result.json').read_text());rows.append(result);write(a.output/'rows.json',rows)
                    if result['status']=='technical_failure':stage('technical_failure_needs_diagnosis',index=i);return
                    if a.entry_smoke and (result['steps']<=0 or result['answered_decisions']!=1 or result['status']=='agent_failure'):stage('entry_smoke_not_passed',index=i);return
                except Exception as e:
                    write(case/'result.json',dict(**item,attempt=attempt,status='technical_failure',error_type=type(e).__name__,error_code=str(e)[:160]))
                    stage('technical_failure_needs_diagnosis',index=i,error_type=type(e).__name__);return
                finally:stop(actor);stop(controller)
        stage('complete',entry_smoke=a.entry_smoke,terminal=len(rows),success=sum(r['status']=='success' for r in rows))
if __name__=='__main__':main()
