import argparse,datetime,fcntl,json,subprocess
from run_queue import ROOT,BASE,env,identity
from admission_wait import alive
from feedback_continue import inspect
from replay import dump
from resume_support import sha

def launch(probe):
    pointer=BASE/'qwen-deploy/latest-memrsi-feedback.json'
    with (BASE/'qwen-deploy/memrsi-feedback-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        old=json.loads(pointer.read_text())
        if alive(old['coordinator']):print(json.dumps(old));return
        if old['version']!='memrsi-feedback-v1.1':raise RuntimeError('existing_recovery_requires_inspection')
        rows,pending,policy,audit=inspect(old['result'],probe)
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out=BASE/'results'/('memrsi-feedback-v1_2-'+stamp);out.mkdir(exist_ok=False)
        dump(out/'source-audit.json',audit)
        dump(out/'code-manifest.json',{str(p.relative_to(ROOT)):sha(p) for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
        with (out/'queue.log').open('xb') as log:
            child=subprocess.Popen(['/home/xi/envs/agent/bin/python',str(ROOT/'feedback_continue.py'),'--parent',old['result'],
               '--probe',str(probe),'--output',str(out/'experiment')],cwd=ROOT,env=env(0),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
        record={'version':'memrsi-feedback-v1.2','resumed_from':old['result'],'code':str(ROOT),'pipeline':str(out),'result':str(out/'experiment'),
                'coordinator':identity(child.pid),'gpus':[0,1,6,7],'planned':120,'retained':len(rows),'new_trials':len(pending)}
        dump(out/'launch.json',record);dump(pointer,record);print(json.dumps(record))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--probe',required=True);a=p.parse_args();launch(a.probe)
