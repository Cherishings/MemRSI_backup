import unittest,tempfile,threading,time,json,asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from parallel_runtime import ParallelExperiment,GpuPool
from replay import dump
import model_provider as provider

class Fake(ParallelExperiment):
    def __init__(self,root):
        self.lock=threading.RLock();self.stop=threading.Event();self.pool=GpuPool((3,4,5),self.stop)
        self.launched=[];self.root=Path(root);self.inflight=set();self.peak=0
    def wait_gateway(self):pass
    def episode(self,row,policy,dest):
        with self.lock:
            assert row['gpu'] not in self.inflight
            self.inflight.add(row['gpu']);self.peak=max(self.peak,len(self.inflight));self.launched.append(row)
        dest.mkdir(parents=True);time.sleep(.03)
        with self.lock:self.inflight.remove(row['gpu'])
        return dict(row,status='success',output=str(dest))
def row(i):return dict(trial_id=f'test-{i}',gpu=0,arm='native',history='unchanged',init=0)
class Tests(unittest.TestCase):
    def test_parallel_unique_gpu_canonical_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            e=Fake(d);rows=[row(i) for i in range(9)];got=e.batch(rows,{},Path(d)/'eval')
            self.assertEqual(e.peak,3);self.assertEqual(len(e.launched),9)
            self.assertEqual([x['trial_id'] for x in got],[r['trial_id'] for r in rows])
            self.assertTrue(all(x['gpu']==0 and x['execution_gpu'] in (3,4,5) for x in got))
            self.assertEqual(json.loads((Path(d)/'eval/schedule.json').read_text()),rows)
    def test_capability_and_exhaustion_never_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            e=Fake(d);out=Path(d)/'eval';out.mkdir();rows=[row(0),row(1)]
            prior=[dict(rows[0],status='decision_failure',attempt=1,output=str(out/'old-a')),
                   dict(rows[1],status='infrastructure_failure',error_code='interrupted_attempt',attempt=3,output=str(out/'old-b'))]
            dump(out/'attempts.json',prior)
            self.assertEqual(len(e.batch(rows,{},out)),2);self.assertEqual(e.launched,[])
    def test_finished_child_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            e=Fake(d);out=Path(d)/'eval';dest=out/'test-0/attempt-01';dest.mkdir(parents=True)
            dump(dest/'result.json',{'status':'success'});dump(dest.with_suffix('.launch.json'),dict(row(0),attempt=1,output=str(dest)))
            got=e.batch([row(0)],{},out)
            self.assertEqual(got[0]['status'],'success');self.assertEqual(e.launched,[])
    def test_retry_remaining_budget(self):
        with tempfile.TemporaryDirectory() as d:
            e=Fake(d);out=Path(d)/'eval';out.mkdir()
            dump(out/'attempts.json',[dict(row(0),status='infrastructure_failure',error_code='interrupted_attempt',attempt=2,output=str(out/'old'))])
            got=e.batch([row(0)],{},out)
            self.assertEqual(got[0]['attempt'],3);self.assertEqual(len(e.launched),1)
    def test_two_model_slots(self):
        async def run():
            with tempfile.TemporaryDirectory() as d,patch.object(provider,'MODEL_LOCK_PATH',Path(d)/'model.lock'):
                count=0;peak=0
                class Client:
                    calls=0
                    def _append(self,*args):pass
                async def request():
                    nonlocal count,peak
                    async with provider.Provider._request_lease(Client()):
                        count+=1;peak=max(peak,count);await asyncio.sleep(.03);count-=1
                await asyncio.gather(*(request() for _ in range(8)))
                self.assertEqual(peak,2)
        asyncio.run(run())
    def test_learning_budget_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json';dump(p,{'calls':5998,'limit':6000})
            def reserve():
                token=provider.LEARNING_LEDGER.set(p)
                try:provider.reserve_learning_call();return True
                except RuntimeError:return False
                finally:provider.LEARNING_LEDGER.reset(token)
            with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:reserve(),range(4)))
            self.assertEqual(sum(results),2);self.assertEqual(json.loads(p.read_text())['calls'],6000)
if __name__=='__main__':unittest.main()
