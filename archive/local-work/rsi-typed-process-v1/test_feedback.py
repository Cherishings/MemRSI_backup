import tempfile,json,unittest
from pathlib import Path
from feedback import build
class FeedbackTests(unittest.TestCase):
 def test_rejects_nontraining_output_before_read(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);t=r/'learning/training';t.mkdir(parents=True)
   rows=[dict(source_id=str(i),arm='joint',repeat=0,policy_sha256='hash',output=str(r/'validation/result')) for i in range(32)]
   (t/'rows.json').write_text(json.dumps(rows));(t/'manifest.json').write_text(json.dumps({'schedule':rows}))
   with self.assertRaisesRegex(AssertionError,'Nontraining'): build(r)
 def test_requires_complete_training(self):
  with tempfile.TemporaryDirectory() as d:
   t=Path(d)/'learning/training';t.mkdir(parents=True)
   (t/'rows.json').write_text('[]');(t/'manifest.json').write_text('{"schedule":[]}')
   with self.assertRaisesRegex(AssertionError,'Training must finish'):build(d)
 def fixture(self,root):
  t=root/'learning/training';t.mkdir(parents=True); rows=[]
  pol=root/'learning/policies';pol.mkdir();(pol/'joint.json').write_text('{}')
  for i in range(32):
   p=t/'replays'/str(i);p.mkdir(parents=True)
   (p/'result.json').write_text('{"policy_sha256":"hash"}')
   rows.append(dict(source_id=str(i),arm='joint' if i<8 else 'parent',status='decision_failure',repeat=0,policy_sha256='hash',output=str(p)))
  (t/'rows.json').write_text(json.dumps(rows));(t/'manifest.json').write_text(json.dumps({'schedule':rows}))
  return t,rows
 def test_includes_all_arm_diagnostics_intact(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);t,rows=self.fixture(root)
   record={'code':'invalid_citation','detail':'x'*2000}
   (Path(rows[31]['output'])/'guidance-advice-failures.jsonl').write_text(json.dumps(record)+'\n')
   result=build(root)
   self.assertEqual(result['training_failure_diagnostics'][0]['diagnostics'][0]['records'],[record])
   self.assertEqual(len(result['joint_contexts']),8)
 def test_duplicate_rows_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);t,rows=self.fixture(root);rows[-1]=rows[0]
   (t/'rows.json').write_text(json.dumps(rows))
   with self.assertRaisesRegex(AssertionError,'Duplicate'):build(root)
