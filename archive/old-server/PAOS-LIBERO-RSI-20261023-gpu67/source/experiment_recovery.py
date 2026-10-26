"""Bounded infrastructure recovery, no retry on capability failure.

Each task has at most three episode attempts including inherited cancelled or
transport-failed attempts. Original evidence stays at original paths. Selected
rows are eventual outcomes; attempts.json is the all-attempt denominator.
"""
import concurrent.futures,json,time
from pathlib import Path
from experiment_v13 import Experiment as Original,TECH
from replay import dump
PARENT=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/portable-runtime-20261023/paos/results/memrsi-feedback-v1_4-20261011T160858Z/experiment')
MAX_ATTEMPTS=3

def retryable(row):
    if row.get('status') in ('success','decision_failure','execution_failure'):return False
    if row.get('status')=='cancelled':
        p=Path(row['output'])/'progress.json'
        data=json.loads(p.read_text()) if p.exists() else {}
        return all(x.get('correct') is True for x in data.get('decisions',[]))
    if row.get('status')!='infrastructure_failure':return False
    for p in Path(row['output']).rglob('model-errors.jsonl'):
        for line in p.read_text().splitlines():
            d=json.loads(line)
            if d.get('http_status') in (408,429,500,502,503,504) and d.get('code')!='generation_output_limit':return True
    return row.get('error_code') in ('worker_timeout',)

class Experiment(Original):
    def batch(self,rows,policies,output,strict_technical=False):
        output=Path(output);output.mkdir(parents=True,exist_ok=False)
        dump(output/'schedule.json',rows);attempts=[];selected=[]
        if output.name=='full-parent':
            inherited=json.loads((PARENT/'learning/full-parent/rows.json').read_text())
            index={r['trial_id']:r for r in rows}
            for r in inherited:
                if r['trial_id'] not in index or any(r.get(k)!=v for k,v in index[r['trial_id']].items()):raise RuntimeError('resume_design_changed')
                attempts.append(dict(r,attempt=1,inherited=True))
        dump(output/'attempts.json',attempts)
        def lane(gpu):
            for row in (r for r in rows if r['gpu']==gpu):
                if self.stop.is_set():return
                with self.lock:prior=[x for x in attempts if x['trial_id']==row['trial_id']]
                last=prior[-1] if prior else None
                if last is not None and not retryable(last):
                    with self.lock:selected.append(last);dump(output/'rows.json',selected)
                    continue
                for attempt in range(len(prior)+1,MAX_ATTEMPTS+1):
                    if self.stop.is_set():return
                    # Transport interruptions do not cancel healthy sibling lanes.
                    if attempt>1 and self.stop.wait(15):return
                    result=self.episode(row,policies.get(row['arm']),output/row['trial_id']/f'attempt-{attempt:02d}')
                    result.update(attempt=attempt,inherited=False)
                    with self.lock:attempts.append(result);dump(output/'attempts.json',attempts)
                    last=result
                    if not retryable(result):break
                if last is None:raise RuntimeError('missing_attempt')
                with self.lock:
                    selected.append(last);dump(output/'rows.json',selected)
        with concurrent.futures.ThreadPoolExecutor(len(self.gpus)) as pool:
            fs=[pool.submit(lane,g) for g in self.gpus]
            for f in concurrent.futures.as_completed(fs):
                try:f.result()
                except BaseException:self.stop.set();raise
        bad=any(r['status'] in TECH for r in selected)
        dump(output/'completion.json',{'planned':len(rows),'terminal':len(selected),'all_attempts':len(attempts),
           'capability_failures_never_retried':True,'max_attempts_including_parent':MAX_ATTEMPTS,
           'status':'interrupted' if len(selected)!=len(rows) else 'technical_hold' if bad else 'completed'})
        if len(selected)!=len(rows):raise RuntimeError('queue_cancelled')
        # Complete the batch before stopping development; do not learn from invalid labels.
        if strict_technical and bad:raise RuntimeError('technical_hold')
        return selected
