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
