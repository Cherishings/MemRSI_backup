"""User-triggered launcher: selected GPU IDs (GPU 2 excluded), no implicit start."""
import argparse
import datetime
import fcntl
import hashlib
import json
import subprocess
from pathlib import Path
from run_queue import ROOT,BASE,env,identity
from replay import dump
from physical_runner import AGENT_PYTHON,LOCKS,PORTS
from twenty_queue import qualification,PHYSICAL_FILES
from learning_v14 import prepare

ORDERS=BASE/'results/memrsi-history-pairs-v1-20261010T074232Z/selected-orders.json'
QUALIFICATION=BASE/'results/memrsi-twenty-qualification-20261011T032643Z'
REVERSE=BASE/'results/memrsi-twenty-qualification-reverse-20261011T033434Z'
POINTER=BASE/'qwen-deploy/latest-memrsi-feedback-v1_4r1.json'

def gpu_ids(values):
    ids=tuple(int(x) for x in values)
    if not ids or len(ids)>7 or len(set(ids))!=len(ids) or any(g not in PORTS or g==2 for g in ids):
        raise ValueError('choose_distinct_gpu_ids_excluding_2')
    return ids

def preflight(gpus):
    core=json.loads((ROOT/'pristine-core-manifest.json').read_text())
    if core['mismatches'] or any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in core['core_sha256'].items()):
        raise RuntimeError('pristine_core_changed')
    old=BASE/'worktrees/memrsi-feedback-v1_2'
    unchanged=list(PHYSICAL_FILES)+['agent_adapter.py','twenty_agent.py',
        'action_catalog.py','memory_budget.py','runtime_config.py','configs/selected-budget.json']
    if any((ROOT/n).read_bytes()!=(old/n).read_bytes() for n in unchanged):raise RuntimeError('shared_runtime_changed')
    previous=(old/'feedback_workflow.py').read_text()
    expected=previous.replace("choices=__import__('feedback_protocol').histories()", "choices=__import__('feedback_protocol').histories()+list(__import__('feedback_protocol').DEVELOPMENT_HISTORIES)")
    if (ROOT/'feedback_workflow.py').read_text()!=expected:raise RuntimeError('workflow_changed_beyond_development_cli')
    from experiment_recovery import PARENT
    from physical_runner import same_process
    oldlaunch=json.loads((PARENT.parent/'launch.json').read_text())
    identities=[oldlaunch['coordinator']]+[json.loads(p.read_text()) for p in (PARENT/'gpu-workers').glob('*.identity.json')]
    previous_rows=json.loads((PARENT/'learning/full-parent/rows.json').read_text())
    identities.extend(r['worker'] for r in previous_rows)
    if any(same_process(i) for i in identities):raise RuntimeError('parent_process_alive')
    oldcode=Path(oldlaunch['code'])
    unchanged_method=['memory_ops.py','memory_design.py','memory_policy.py','learning_v14.py','feedback_protocol.py']
    if any((ROOT/n).read_bytes()!=(oldcode/n).read_bytes() for n in unchanged_method):raise RuntimeError('method_changed')
    if (PARENT/'learning/report.json').exists():raise RuntimeError('parent_learning_already_terminal')
    qualification(QUALIFICATION,REVERSE)
    dev,valid=prepare()
    if not ORDERS.is_file():raise RuntimeError('orders_missing')
    actual={int(x.strip()) for x in subprocess.check_output(['nvidia-smi','--query-gpu=index','--format=csv,noheader'],text=True).splitlines()}
    if not set(gpus)<=actual:raise RuntimeError('selected_gpu_missing')
    return {'status':'preflight_passed','gpus':list(gpus),'core_files':len(core['core_sha256']),
        'unchanged_runtime_files':unchanged,'development_windows':len(dev),'validation_windows':len(valid),
        'policy_seed':'task-record compiler plus exact-quote guidance; manual seed not learned',
        'starts_models':False,'calls_gateway':False}

def main(a):
    gpus=gpu_ids(a.gpus)
    audit=preflight(gpus)
    if a.check_only:print(json.dumps(audit));return
    with (BASE/'qwen-deploy/memrsi-feedback-v1_4r1-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if POINTER.exists():
            prior=json.loads(POINTER.read_text())
            print(json.dumps({'status':'existing_run_no_duplicate','launch':prior,
                'instruction':'Inspect the existing run. No retry counts or experiment directories were reset.'}));return
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out=BASE/'results'/('memrsi-feedback-v1_4r1-'+stamp);out.mkdir(exist_ok=False)
        dump(out/'preflight.json',audit)
        dump(out/'code-manifest.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts})
        record={'version':'memrsi-feedback-v1.4r1','code':str(ROOT),'pipeline':str(out),
            'result':str(out/'experiment'),'gpus':list(gpus),'status':'launching','model':'gpt-5.6-luna'}
        dump(POINTER,record);dump(out/'launch.json',record)
        cmd=[AGENT_PYTHON,str(ROOT/'pipeline_v14r1.py'),'--output',str(out/'experiment'),
            '--orders',str(ORDERS),'--qualification',str(QUALIFICATION),'--reverse',str(REVERSE),
            '--gpus',*[str(g) for g in gpus]]
        with (out/'pipeline.lock').open('a') as lease, (out/'queue.log').open('xb') as log:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            child=None
            try:
                child=subprocess.Popen(cmd,cwd=ROOT,env=env(gpus[0]),stdout=log,stderr=log,
                    stdin=subprocess.DEVNULL,start_new_session=True,pass_fds=(lease.fileno(),))
                record.update(status='started',coordinator=identity(child.pid))
                dump(POINTER,record);dump(out/'launch.json',record)
            except BaseException:
                if child is not None:
                    from run_queue import stop_group
                    stop_group(child)
                record['status']='launch_failed';dump(POINTER,record);dump(out/'launch.json',record)
                raise RuntimeError('launch_failed') from None
        print(json.dumps(record))

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Start new MemRSI v1.4r1 on selected GPUs excluding GPU 2; existing experiments untouched.')
    p.add_argument('--gpus',nargs='+',type=int,required=True,metavar='GPU')
    p.add_argument('--check-only',action='store_true',help='Offline preflight only; no model/robot launched')
    a=p.parse_args()
    try:main(a)
    except ValueError as exc:p.error(str(exc))
