import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import regression_evolution as m
from stream_design import SEED_PROCEDURES,compile_procedures
from replay import dump

class CacheAudit(unittest.TestCase):
    def build(self,p):
        dump(p/'budget.json',{'budget':1})
        for cycle in (0,1):
            d=p/'learning'/f'cycle-{cycle}'/'probes';rows=[]
            sources=[{'id':f'c{cycle}-{i}','sha256':'unchanged'} for i in range(4)]
            dump(d/'manifest.json',{'parent':compile_procedures(SEED_PROCEDURES),'sources':sources})
            for src in sources:
                for rep in (0,1):
                    r=dict(status='completed',source=src['id'],correct=7,answered=7,planned=7)
                    dump(d/f"{src['id']}-r{rep}-parent"/'result.json',r)
                    rows.append(dict(r,case=src['id'],repeat=rep,policy='parent'))
            dump(d/'rows.json',rows)
    def test_exact_cache_plan_and_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.build(p)
            with patch.object(m,'fixture',side_effect=lambda s:dict(source=s,sha256='unchanged')):
                jobs=m.plan(p,p/'budget.json')
                self.assertEqual(len(jobs),12)
                self.assertEqual(sum(j['cycle']==0 for j in jobs),8)
                # A cache is rejected if its policy, fixture, budget, or row differs.
                d=p/'learning/cycle-0/probes';value=json.loads((d/'manifest.json').read_text())
                value['parent']['update']='modified';dump(d/'manifest.json',value)
                with self.assertRaisesRegex(RuntimeError,'cached_parent_changed'):m.plan(p,p/'budget.json')
            self.build(p)
            with patch.object(m,'fixture',return_value=dict(sha256='different')):
                with self.assertRaisesRegex(RuntimeError,'cached_source_changed'):m.plan(p,p/'budget.json')
            dump(p/'other-budget.json',{'budget':2})
            with self.assertRaisesRegex(RuntimeError,'cached_budget_changed'):m.plan(p,p/'other-budget.json')
    def test_cached_runtime_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);old=p/'old';new=p/'new';old.mkdir();new.mkdir()
            (old/'actor.py').write_text('unchanged');(new/'actor.py').write_text('unchanged')
            with patch.object(m,'ROOT',new):
                self.assertEqual(len(m.verify_runtime(old)),1)
                (new/'actor.py').write_text('different')
                with self.assertRaisesRegex(RuntimeError,'cached_runtime_changed'):m.verify_runtime(old)

class Execution(unittest.IsolatedAsyncioTestCase):
    async def test_parent_not_reexecuted_and_candidate_failure_retained(self):
        called=[]
        async def fake(f,*a):
            called.append(f['id']);return dict(status='decision_failure',correct=0,answered=1,planned=7)
        class C:
            def state(self,*a,**k):pass
            def wait_gateway(self):pass
        jobs=[dict(fixture={'id':'source'},repeat=r,cache=f'cache{r}',parent=dict(status='completed',correct=7,answered=7,planned=7)) for r in (0,1)]
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'replay_case',fake):
            rows=await m.evaluate_jobs(jobs,tmp,{}, {},C())
        self.assertEqual(len(called),2);self.assertEqual(len(rows),4)
        self.assertFalse(m.select(rows,2)['accepted'])
        self.assertTrue(all(not r['new_execution'] for r in rows if r['policy']=='parent'))

if __name__=='__main__':unittest.main()
