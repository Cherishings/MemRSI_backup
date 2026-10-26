import unittest
from collections import Counter
from compare_v14 import planned_rows,pair_summary
class Comparison(unittest.TestCase):
 def test_complete_balanced_eighty(self):
  rows=planned_rows((0,1,3,4,5,6,7))
  self.assertEqual(len(rows),80);self.assertEqual(len({r['trial_id'] for r in rows}),80)
  self.assertEqual(Counter(r['arm'] for r in rows),{'native':40,'fixed':40})
  self.assertEqual(Counter(rows[i]['arm'] for i in range(0,80,2)),{'native':20,'fixed':20})
  for i in range(0,80,2):
   a,b=rows[i:i+2]
   self.assertEqual((a['condition'],a['repeat'],a['gpu'],a['history'],a['init']),
                    (b['condition'],b['repeat'],b['gpu'],b['history'],b['init']))
  pairs=pair_summary([dict(r,status='success') for r in rows])
  self.assertEqual(len(pairs),40);self.assertTrue(all(r['complete_pair'] for r in pairs))
 def test_no_learning_or_success_early_stop(self):
  import inspect,compare_v14
  s=inspect.getsource(compare_v14.main)
  self.assertNotIn('learn(',s)
  self.assertIn("out/'evaluation',False",s)
