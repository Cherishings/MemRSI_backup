import argparse,datetime,fcntl,hashlib,json,subprocess
from pathlib import Path
from run_queue import ROOT,BASE,env,identity
from replay import dump
from physical_runner import AGENT_PYTHON
from learning_v13 import prepare
PRIOR=BASE/'results/memrsi-feedback-v1_5-20261011T183452Z/experiment'
POINTER=BASE/'qwen-deploy/latest-memrsi-feedback-v1_5r1.json'
AFTER=BASE/'qwen-deploy/latest-memrsi-feedback-v1_4compare.json'

def preflight():
    old=BASE/'worktrees/memrsi-feedback-v1_4compare'
    core=json.loads((ROOT/'pristine-core-manifest.json').read_text())
    if core['mismatches'] or any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in core['core_sha256'].items()):
        raise RuntimeError('pristine_core_changed')
    changed=[p.name for p in old.glob('*.py') if p.read_bytes()!=(ROOT/p.name).read_bytes()]
    if set(changed)!={'feedback_protocol.py','feedback_workflow.py'}:raise RuntimeError('unexpected_shared_change')
    expected=(old/'feedback_workflow.py').read_text().replace(
        "choices=__import__('feedback_protocol').histories()+list(__import__('feedback_protocol').DEVELOPMENT_HISTORIES)",
        "choices=__import__('feedback_protocol').histories()+__import__('feedback_protocol').transfer_histories()+list(__import__('feedback_protocol').DEVELOPMENT_HISTORIES)")
    if (ROOT/'feedback_workflow.py').read_text()!=expected:raise RuntimeError('physical_workflow_changed')
    from physical_runner import same_process
    prior_launch=json.loads((PRIOR.parent/'launch.json').read_text())
    if same_process(prior_launch['coordinator']):raise RuntimeError('prior_alive')
    if json.loads((PRIOR/'report.json').read_text()).get('error_code')!='optimizer_schema_failure':raise RuntimeError('unexpected_prior_failure')
    old_evolution=Path(prior_launch['code'])
    for n in ('memory_design.py','memory_policy.py','memory_ops.py','structured_feedback.py','feedback_learning.py','feedback_protocol.py','feedback_workflow.py','model_provider.py'):
        if (ROOT/n).read_bytes()!=(old_evolution/n).read_bytes():raise RuntimeError('actor_or_scoring_changed')
    dev,valid=prepare()
    parent=json.loads(AFTER.read_text())
    if not (Path(parent['result'])/'budget.json').exists():raise RuntimeError('parent_not_initialized')
    return dict(status='preflight_passed',unchanged_core_files=len(core['core_sha256']),
                development_windows=len(dev),validation_windows=len(valid),starts_gpu=False)

def main(a):
    if not a.gpus or len(set(a.gpus))!=len(a.gpus) or set(a.gpus)-{0,1,3,4,5,6,7}:raise ValueError('invalid_gpu')
    audit=preflight()
    if a.check_only:print(json.dumps(audit));return
    with (BASE/'qwen-deploy/memrsi-feedback-v1_5r1-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if POINTER.exists():print(json.dumps({'status':'existing_run_no_duplicate','pointer':str(POINTER)}));return
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out=BASE/'results'/('memrsi-feedback-v1_5r1-'+stamp);out.mkdir(exist_ok=False)
        dump(out/'preflight.json',audit)
        dump(out/'code-manifest.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts})
        # Snapshot prerequisite identity; later pointer changes cannot redirect the queue.
        dump(out/'after.json',json.loads(AFTER.read_text()))
        record=dict(version='v1.5r1',code=str(ROOT),pipeline=str(out),result=str(out/'experiment'),gpus=a.gpus,status='launching')
        dump(POINTER,record);dump(out/'launch.json',record)
        with (out/'pipeline.lock').open('a') as lease,(out/'queue.log').open('xb') as log:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            child=subprocess.Popen([AGENT_PYTHON,str(ROOT/'pipeline_v15.py'),'--output',str(out/'experiment'),
               '--after',str(out/'after.json'),'--resume-learning',str(PRIOR/'learning'),'--gpus',*[str(g) for g in a.gpus]],cwd=ROOT,env=env(a.gpus[0]),
               stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,pass_fds=(lease.fileno(),))
            record.update(status='started',coordinator=identity(child.pid));dump(out/'launch.json',record);dump(POINTER,record)
        print(json.dumps(record))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gpus',type=int,nargs='+',required=True);p.add_argument('--check-only',action='store_true')
    main(p.parse_args())
