"""External scheduler: frozen learning order; two fixed GPU shards for formal tests."""
import sys, importlib.util, copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import setproctitle
setproctitle.setproctitle('robot')
code=Path(sys.argv.pop(1));sys.path.insert(0,str(code))
spec=importlib.util.spec_from_file_location('frozen_study',code/'run_study.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original_batch=m.batch

def batch(a,phase,methods):
    if phase!='test':return original_batch(a,phase,methods)
    gpu_pair={'rmbench':(6,4),'remem':(5,7)}[a.benchmark]
    seeds=list(m.SPLITS[phase]);tasks=[[],[]]
    for i,seed in enumerate(seeds):
        order=list(methods)
        if i%2:order.reverse()
        tasks[i%2].extend((seed,method) for method in order)
    def shard(index):
        local=copy.copy(a);local.gpu=gpu_pair[index];out=[]
        for seed,method in tasks[index]:
            row,path=m.one(local,phase,method,methods[method],seed)
            out.append((seed,method,row,path))
            m.write(a.output/f'formal-gpu{local.gpu}-progress.json',dict(phase=phase,gpu=local.gpu,latest_seed=seed,latest_method=method,completed=len(out),planned=len(tasks[index])))
        return out
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(shard,i) for i in range(2)]
        records=[item for f in futures for item in f.result()]
    by={(s,method):(row,path) for s,method,row,path in records}
    rows=[];paths={method:{} for method in methods}
    for i,seed in enumerate(seeds):
        order=list(methods)
        if i%2:order.reverse()
        for method in order:
            row,path=by[seed,method];rows.append(row);paths[method][seed]=path
    return rows,paths
m.batch=batch
original_one=m.one

def one(a,phase,method,policy,seed):
    ph=m.policy_sha256(m.read(policy)) if method!='native' else m.run_trial.native_policy_hash()
    expected='5fd015e03e5258978c2f09104dcdf89224187cce23253e8e268139bb229140f0'
    if a.benchmark=='rmbench' and phase=='development' and seed==2008 and method!='native' and ph==expected:
        folder=Path('/data/stormlab/xi/robot/runs/official-memory-gpu56-20261020/rmbench/trajectories/development')/expected/'2008'
        row=m.checked_cached_row(a,phase,method,ph,seed,folder)
        return dict(row,method=method),folder
    return original_one(a,phase,method,policy,seed)
m.one=one
if __name__=='__main__':m.main()
