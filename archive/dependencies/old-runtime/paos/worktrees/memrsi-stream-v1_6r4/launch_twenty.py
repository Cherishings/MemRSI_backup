"""Single registered, versioned launch after live regression gates pass."""
import argparse, datetime, fcntl, hashlib, json, subprocess
from pathlib import Path
from run_queue import ROOT, BASE, dump, identity, env, stop_group
from admission_wait import alive

VERSION='memrsi-twenty-v3'
SOURCE=BASE/'results/memrsi-mission-stress-v1-20261010T085842Z'
ORDERS=BASE/'results/memrsi-history-pairs-v1-20261010T074232Z/selected-orders.json'

def main(a):
    with (BASE/'qwen-deploy/memrsi-twenty-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for prior in (BASE/'results').glob(VERSION+'-*/launch.json'):
            r=json.loads(prior.read_text())
            if any(alive(x) for x in r.get('processes',{}).values()):
                print(json.dumps({'status':'already_running','launch':str(prior)}));return
            # Interrupted experimental runs are not reset automatically.
            if r.get('status')!='launch_failed':
                raise RuntimeError('existing_versioned_launch_requires_inspection')
        for report in (a.regression,):
            if not json.loads(Path(report).read_text()).get('passed'):
                raise RuntimeError('live_regression_gate_failed')
        proof=json.loads((ROOT/'pristine-core-manifest.json').read_text())
        if proof['mismatches'] or any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h
                 for n,h in proof['core_sha256'].items()):
            raise RuntimeError('pristine_core_changed')
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out=BASE/'results'/f'{VERSION}-{stamp}';out.mkdir(exist_ok=False)
        dump(out/'code-manifest.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
        dump(out/'repair-scope.json',{'old_results_preserved':True,'original_core_files':len(proof['core_sha256']),
            'regression':a.regression,
            'engineering_changes':['single public action catalog','MemRSI archival access to public tool scope',
                'remove model semantic-review hard veto; G remains advice and actor makes decision'],
            'learned_changes':'none at launch; separately evaluated development evolution may retain or change G/U',
            'native_archive_prompt':'unchanged','physical_executor':'unchanged',
            'superseded_pipeline':'/data/stormlab/xi/paos/results/memrsi-twenty-v2-20261011T042100Z',
            'retained_failure':'MemRSI completed two physical sessions; independent reviewer then falsely vetoed table-B guidance.',
            'development_learning_source':str(SOURCE),'evaluation_feedback_used_for_learning':False})
        py='/home/xi/envs/agent/bin/python'
        commands={
            'evolution':[py,str(ROOT/'evolution.py'),'--source',str(SOURCE),'--output',str(out/'evolution')],
            'queue':[py,str(ROOT/'twenty_queue.py'),'--output',str(out/'experiment'),
                '--qualification',str(BASE/'results/memrsi-twenty-qualification-20261011T032643Z'),
                '--reverse',str(BASE/'results/memrsi-twenty-qualification-reverse-20261011T033434Z'),
                '--budget',str(ROOT/'configs/selected-budget.json'),'--orders',str(ORDERS),
                '--base-policy',str(ROOT/'configs/base-policy.json'),
                '--evolution-policy',str(out/'evolution/final-policy.json')]}
        record={'version':VERSION,'code':str(ROOT),'result':str(out/'experiment'),'pipeline':str(out),
                'status':'launching','processes':{},'gpus':[6,7],'model':'gpt-5.6-luna','planned_trials':12}
        children=[]
        with (out/'pipeline.lock').open('a') as lease:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            dump(out/'launch.json',record)
            try:
                for name,cmd in commands.items():
                    with (out/(name+'.log')).open('xb') as log:
                        child=subprocess.Popen(cmd,cwd=ROOT,env=env(6),stdin=subprocess.DEVNULL,
                            stdout=log,stderr=log,start_new_session=True,pass_fds=(lease.fileno(),))
                    children.append(child);record['processes'][name]=identity(child.pid)
                    dump(out/'launch.json',record)
                record['status']='running';dump(out/'launch.json',record)
                dump(BASE/'qwen-deploy/latest-twenty-experiment.json',dict(record,**record['processes']['queue']))
            except BaseException:
                for child in children:
                    if child.poll() is None:stop_group(child)
                record['status']='launch_failed';dump(out/'launch.json',record);raise
        print(json.dumps(record))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--regression',required=True)
    main(p.parse_args())
