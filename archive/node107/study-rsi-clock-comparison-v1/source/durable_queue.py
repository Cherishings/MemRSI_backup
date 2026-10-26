"""Resumable attempt ledger. Capability failures are terminal, never best-of retries."""
import json, time, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from experiment_v13 import Experiment
from experiment_recovery import retryable
from physical_runner import same_process
from replay import dump

GPU_IDS=(0,1,2)
def read(p,default=None):
    p=Path(p);return json.loads(p.read_text()) if p.exists() else default

def retry(row):
    if row['status']=='cancelled':return True  # administrative stop, counted in total3
    if retryable(row):return True
    if row['status']!='infrastructure_failure':return False
    if row.get('error_code')=='interrupted_attempt':return True
    for p in Path(row['output']).rglob('model-errors.jsonl'):
        for s in p.read_text().splitlines():
            d=json.loads(s)
            if d.get('exception_type')=='APIConnectionError' and d.get('http_status') is None:return True
    return False

def unique_attempts(rows):
    out=[];seen=set()
    for r in rows:
        key=r['output']
        if key not in seen:out.append(r);seen.add(key)
    return out

class DurableExperiment(Experiment):
    def __init__(self,*args,health_url='http://127.0.0.1:19099/health',**kw):
        # Experiment creates this directory, so allow resuming its metadata only.
        out=Path(args[0]);workers=out/'gpu-workers'
        for active in read(out/'progress.json',{}).get('active',{}).values():
            if active.get('worker') and same_process(active['worker']):raise RuntimeError('owned_worker_still_alive')
        if workers.exists():
            for p in workers.glob('*.identity.json'):
                if same_process(read(p)):raise RuntimeError('owned_policy_still_alive')
            archive=out/('gpu-workers-previous-'+str(time.time_ns()));workers.rename(archive)
        super().__init__(*args,**kw);self.health_url=health_url
    def wait_gateway(self):
        while not self.stop.is_set():
            try:
                with urllib.request.urlopen(self.health_url,timeout=8) as f:d=json.load(f)
                if d.get('model')=='gpt-5.6-luna' and d.get('gateway_version')=='memory-v3-tool-choice':return
                raise RuntimeError('common_gateway_mismatch')
            except (OSError,ValueError):pass
            self.state('waiting_gateway_no_trial_started');self.stop.wait(30)
        raise RuntimeError('queue_cancelled')
    def episode(self,*a,**kw):
        self.wait_gateway();return super().episode(*a,**kw)
    def batch(self,rows,policies,output,strict_technical=False,inherited=()):
        out=Path(output);out.mkdir(parents=True,exist_ok=True)
        previous=read(out/'schedule.json')
        if previous is not None and previous!=rows:raise RuntimeError('schedule_changed')
        dump(out/'schedule.json',rows)
        attempts=unique_attempts(list(inherited)+read(out/'attempts.json',[]))
        ids={r['trial_id'] for r in rows}
        attempts=[r for r in attempts if r['trial_id'] in ids]
        # A launch is journaled before the child starts. A crash cannot reset its count.
        for row in rows:
            folder=out/row['trial_id']
            for launch in sorted(folder.glob('attempt-*.launch.json')):
                ticket=read(launch);dest=Path(ticket['output'])
                if any(r['output']==str(dest) for r in attempts):continue
                worker=read(dest/'worker-identity.json')
                if worker and same_process(worker):raise RuntimeError('episode_still_alive')
                result=read(dest/'result.json',{'status':'infrastructure_failure','error_code':'interrupted_attempt'})
                attempts.append(dict(result,**row,output=str(dest),attempt=ticket['attempt'],inherited=False))
        dump(out/'attempts.json',attempts)
        selected={}
        def lane(gpu):
            for row in (r for r in rows if r['gpu']==gpu):
                if self.stop.is_set():return
                with self.lock:prior=[r for r in attempts if r['trial_id']==row['trial_id']]
                last=prior[-1] if prior else None
                if last is None or retry(last):
                    for n in range(len(prior)+1,4):
                        if self.stop.is_set():return
                        self.wait_gateway()
                        dest=out/row['trial_id']/f'attempt-{n:02d}'
                        dump(dest.with_suffix('.launch.json'),dict(row,output=str(dest),attempt=n))
                        last=self.episode(row,policies.get(row['arm']),dest)
                        last.update(attempt=n,inherited=False)
                        with self.lock:attempts.append(last);dump(out/'attempts.json',attempts)
                        if not retry(last):break
                        if self.stop.wait(15):return
                if last is not None:
                    with self.lock:
                        selected[row['trial_id']]=last
                        dump(out/'rows.json',[selected[r['trial_id']] for r in rows if r['trial_id'] in selected])
        with ThreadPoolExecutor(len(self.gpus)) as pool:
            fs=[pool.submit(lane,g) for g in self.gpus]
            for f in fs:f.result()
        result=[selected[r['trial_id']] for r in rows if r['trial_id'] in selected]
        done=len(result)==len(rows)
        dump(out/'completion.json',{'planned':len(rows),'terminal':len(result),'all_attempts':len(attempts),
            'status':'completed' if done else 'interrupted','max_attempts':3,'capability_reruns':0})
        if not done:raise RuntimeError('queue_cancelled')
        return result
