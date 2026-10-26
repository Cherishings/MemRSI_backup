import unittest,copy
from evolve_v15 import select,merge_design
from memory_design import SEED,policy
from memory_policy import combinations,digest
from feedback_protocol import transfer_histories,histories,old_histories,v13_histories,DEVELOPMENT_HISTORIES,plan
from pipeline_v15 import schedule,summarize

def score(a,b,tokens=100,invalid=0):
    return dict(correct=a+b,per_case={'a':a,'b':b},invalid=invalid,cost_complete=True,tokens=tokens)

class Tests(unittest.TestCase):
    def test_credit_selection_rejects_regression_and_technical(self):
        parent=score(1,1)
        self.assertIsNone(select(parent,{'joint':score(0,3)}))
        self.assertIsNone(select(parent,{'joint':score(2,2,invalid=1)}))
        self.assertIsNone(select(parent,{'joint':score(2,2,tokens=151)}))
        self.assertEqual(select(parent,{'joint':score(2,1),'guidance_only':score(2,1)}),'guidance_only')
    def test_arrow_merge_matches_actual_policy(self):
        d=copy.deepcopy(SEED);d['fields']+=['uncertainty'];d['read_focus']='Read evidence.';d['retention_focus']='Keep evidence.'
        variants=combinations(policy(SEED),policy(d))
        for name in ('guidance_only','update_only','joint'):
            self.assertEqual(digest(policy(merge_design(SEED,d,name))),digest(variants[name]))
    def test_fresh_histories_and_paired_physics(self):
        fresh=transfer_histories();self.assertEqual(len(fresh),4)
        self.assertFalse(set(fresh)&set(histories()+old_histories()+v13_histories()+list(DEVELOPMENT_HISTORIES)))
        rows=schedule([0,1,3,4,5,6,7],True);self.assertEqual(len(rows),24)
        for h in fresh:self.assertEqual(len(plan(h)['sessions']),20)
        for cond in {r['condition'] for r in rows}:
            p=[r for r in rows if r['condition']==cond]
            self.assertEqual({r['arm'] for r in p},{'native','fixed','candidate'})
            self.assertEqual(len({(r['gpu'],r['history'],r['init']) for r in p}),1)
        self.assertEqual(summarize([],rows)['candidate']['planned_checkpoints'],56)
        self.assertIsNone(summarize([],rows)['candidate']['accuracy_given_reached'])

if __name__=='__main__':unittest.main()
