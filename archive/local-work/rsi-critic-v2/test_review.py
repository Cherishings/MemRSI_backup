import unittest
from review import accepted,CHECKS
class ReviewTests(unittest.TestCase):
 def value(self):return {k:v for key in CHECKS for k,v in [(key,'pass'),(key+'_reason','Requirement preserved.')]}
 def test_all_required(self):self.assertTrue(accepted(self.value()))
 def test_each_rejection_wins(self):
  for k in CHECKS:
   x=self.value();x[k]='fail';self.assertFalse(accepted(x))
 def test_boolean_and_overall_verdict_rejected(self):
  for change in [{'generic':True},{'verdict':'accept'},{'generic':'accept'},{'generic_reason':''}]:
   x=self.value();x.update(change)
   with self.assertRaises(ValueError):accepted(x)
