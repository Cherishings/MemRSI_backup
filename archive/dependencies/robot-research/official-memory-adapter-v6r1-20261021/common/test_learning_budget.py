import json,tempfile,unittest
from pathlib import Path
from learning_budget import charge,LearningBudgetExhausted,BASE_USED,BASE_LIMIT
class Budget(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'ledger.json'
 def tearDown(self):self.tmp.cleanup()
 def test_initial_inherits(self):self.assertEqual(charge(self.p,'development','a'),8987)
 def test_cannot_reset(self):
  self.p.write_text(json.dumps({'inherited_used':8986,'used':0,'authorized_limit':9745,'entries':[]}))
  with self.assertRaises(RuntimeError):charge(self.p,'development','a')
 def test_cannot_expand_without_authorization(self):
  self.p.write_text(json.dumps({'inherited_used':8986,'used':8986,'authorized_limit':13745,'entries':[]}))
  with self.assertRaises(RuntimeError):charge(self.p,'development','a')
 def test_exhausted_before_call(self):
  self.p.write_text(json.dumps({'inherited_used':8986,'used':9745,'authorized_limit':9745,'entries':[]}))
  with self.assertRaises(LearningBudgetExhausted):charge(self.p,'development','a')
  self.assertEqual(json.loads(self.p.read_text())['used'],9745)
if __name__=='__main__':unittest.main()
