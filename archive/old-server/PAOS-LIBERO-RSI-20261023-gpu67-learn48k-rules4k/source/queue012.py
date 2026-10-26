"""Execution-only relocation to GPUs 0/1/2. Frozen policies and all attempts kept."""
import argparse,json,os,signal,threading,time,urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from replay import dump
from run_queue import identity
from experiment_recovery import Experiment,retryable
from pipeline_v15 import schedule,summarize
from memory_policy import digest

COMPARISON=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/portable-runtime-20261023/paos/results/memrsi-feedback-v1_4compare-20261011T182534Z/experiment')
EVOLUTION=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/portable-runtime-20261023/paos/results/memrsi-feedback-v1_5r1-20261011T203525Z/experiment')
GPUS=(0,1,2)

def read(p):return json.loads(p.read_text())
def disconnected(r):
    if r['status']!='infrastructure_failure':return False
    for p in Path(r['output']).rglob('model-errors.jsonl'):
        for line in p.read_text().splitlines():
            d=json.loads(line)
            if d.get('exception_type')=='APIConnectionError' and d.get('http_status') is None:return True
    return False

def recovery_plan():
    rows=read(COMPARISON/'evaluation/rows.json');attempts=read(COMPARISON/'evaluation/attempts.json')
    counts=Counter(x['trial_id'] for x in attempts)
    selected=[r for r in rows if (disconnected(r) or retryable(r)) and counts[r['trial_id']]<3]
    original=read(COMPARISON/'manifest.json')['schedule'];ids={r['trial_id'] for r in selected}
    # Preserve original order and all condition/arm identifiers; only GPU assignment changes.
    result=[]
    conditions={r['condition']+str(r['repeat']):i for i,r in enumerate(original)}
    for row in original:
        if row['trial_id'] in ids:
            row=dict(row,gpu=GPUS[conditions[row['condition']+str(row['repeat'])]%3]);result.append(row)
    return result,attempts,rows

class Recovering(Experiment):
    def wait_gateway(self):
        while not self.stop.is_set():
            try:
                with urllib.request.urlopen('http://127.0.0.1:19095/health',timeout=8) as r:
                    if json.load(r).get('model')=='gpt-5.6-luna':return
            except (OSError,ValueError):pass
            self.state('waiting_gateway_no_new_trial',gpus=list(GPUS))
            self.stop.wait(30)
        raise RuntimeError('queue_cancelled')
    def episode(self,*args,**kwargs):
        self.wait_gateway()
        return super().episode(*args,**kwargs)
    def recover(self,rows,policies,out,old_attempts,old_rows):
        out=Path(out);out.mkdir();attempts=[dict(r,inherited=True) for r in old_attempts]
        selected={r['trial_id']:r for r in old_rows};lock=self.lock
        dump(out/'schedule.json',rows);dump(out/'attempts.json',attempts)
        dump(out/'rows.json',list(selected.values()))
        def lane(gpu):
            for row in (r for r in rows if r['gpu']==gpu):
                with lock:prior=[r for r in attempts if r['trial_id']==row['trial_id']]
                for n in range(len(prior)+1,4):
                    if self.stop.is_set():return
                    r=self.episode(row,policies.get(row['arm']),out/row['trial_id']/f'attempt-{n:02d}')
                    r.update(attempt=n,inherited=False)
                    with lock:
                        attempts.append(r);selected[row['trial_id']]=r
                        dump(out/'attempts.json',attempts);dump(out/'rows.json',list(selected.values()))
                    if not (disconnected(r) or retryable(r)):break
                    if self.stop.wait(15):return
        with ThreadPoolExecutor(3) as pool:
            futures=[pool.submit(lane,g) for g in GPUS]
            for f in futures:f.result()
        dump(out/'completion.json',{'status':'cancelled' if self.stop.is_set() else 'completed',
            'original_cases':80,'recovery_cases':len(rows),'all_attempts':len(attempts),
            'max_case_attempts':max(Counter(r['trial_id'] for r in attempts).values()),
            'original_results_not_overwritten':True})
        return list(selected.values())

def main(a):
    out=Path(a.output);out.mkdir(exist_ok=False);stop=threading.Event();e=None
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    dump(out/'coordinator.json',identity(os.getpid()))
    report={'status':'failed'}
    try:
        for name in ('selected-orders.json','budget.json'):(out/name).write_bytes((EVOLUTION/name).read_bytes())
        policies={}
        for arm in ('fixed','candidate'):
            d=read(EVOLUTION/f'policies/{arm}.json');dump(out/f'policies/{arm}.json',d);policies[arm]=out/f'policies/{arm}.json'
        if digest(read(policies['candidate']))!=read(EVOLUTION/'learning/candidate-freeze.json')['sha256']:raise RuntimeError('candidate_mismatch')
        transfer=schedule(GPUS,True);recovery,prior,old=recovery_plan()
        dump(out/'manifest.json',{'gpus':list(GPUS),'version':'012-execution-resume','learning_rerun':False,
            'frozen_learning':str(EVOLUTION),'transfer_schedule':transfer,'recovery_schedule':recovery,
            'prior_comparison':str(COMPARISON),'all_prior_attempts':len(prior),'max_attempts_per_case':3,
            'capability_failure_retries':0,'physical_and_memory_parameters_unchanged':True,
            'connection_failures_retryable':True,'no_new_trial_while_gateway_down':True})
        e=Recovering(out,GPUS,out/'selected-orders.json',out/'budget.json',stop)
        e.wait_gateway();e.acquire()
        rows=e.batch(transfer,policies,out/'transfer',False)
        dump(out/'transfer-summary.json',summarize(rows,transfer))
        if stop.is_set():raise RuntimeError('queue_cancelled')
        rows=e.recover(recovery,policies,out/'comparison-recovery',prior,old)
        from feedback_queue import summarize as summarize_comparison
        summary=summarize_comparison(rows,read(COMPARISON/'manifest.json')['schedule'])
        dump(out/'comparison-summary.json',summary)
        report={'status':'completed','transfer_planned':24,'recovered_comparison_cases':len(recovery)}
    except Exception as exc:
        report={'status':'cancelled' if stop.is_set() else 'failed','error_type':type(exc).__name__}
    finally:
        if e:e.close()
        dump(out/'report.json',report)
    return 0 if report['status']=='completed' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);raise SystemExit(main(p.parse_args()))
