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
if __name__=='__main__':m.main()
