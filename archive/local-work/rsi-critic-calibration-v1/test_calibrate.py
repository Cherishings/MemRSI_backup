import unittest
import calibrate,governance
class CalibrationTests(unittest.TestCase):
 def test_controls_fixed_distinct_and_balanced(self):
  cases=calibrate.controls({'guidance':'Generic parent.','update':'Preserve public obligations.'})
  self.assertEqual(len(cases),6);self.assertEqual(len({x['candidate']['guidance'] for x in cases}),6)
  self.assertEqual(sum(x['expected'].get('all_pass',False) for x in cases),3)
 def test_protocol_failure_never_counts_as_correct_rejection(self):
  self.assertFalse(calibrate.evaluate(None,{'code':'generation_output_limit'},{},{'must_fail':'generic'})['correct'])
 def test_expected_outcomes_scored_without_changing_verdict(self):
  value={}
  for key in governance.CHECKS:value.update({key:'pass',key+'_reason':'Consistent with criterion.',key+'_quote':''})
  c={'guidance':'Do not execute.','update':'Keep obligations.'}
  self.assertTrue(calibrate.evaluate(value,None,c,{'all_pass':True})['correct'])
  self.assertFalse(calibrate.evaluate(value,None,c,{'must_fail':'preserves_user_authority'})['correct'])
