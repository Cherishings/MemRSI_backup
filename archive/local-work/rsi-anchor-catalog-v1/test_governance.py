import unittest
import learn
from governance import CHECKS,SCHEMA,verdict
class ContractTests(unittest.TestCase):
 def v(self):return {k:v for key in CHECKS for k,v in [(key,'pass'),(key+'_reason','No violation'),(key+'_quote','')]}
 def test_empty_pass_quotes_valid(self):self.assertTrue(verdict(self.v(),{'guidance':'generic instructions'},learn.validate_submission))
 def test_reject_nonexistent_quote(self):
  x=self.v();x.update(generic='fail',generic_quote='invented')
  with self.assertRaisesRegex(ValueError,'without_candidate'):verdict(x,{'guidance':'actual'},learn.validate_submission)
 def test_supported_failure_stays_rejected(self):
  x=self.v();x.update(generic='fail',generic_quote='specific task')
  self.assertFalse(verdict(x,{'guidance':'execute specific task'},learn.validate_submission))
 def test_no_implicit_pass_for_missing_field(self):
  x=self.v();del x['generic_quote']
  with self.assertRaises(ValueError):verdict(x,{},learn.validate_submission)
