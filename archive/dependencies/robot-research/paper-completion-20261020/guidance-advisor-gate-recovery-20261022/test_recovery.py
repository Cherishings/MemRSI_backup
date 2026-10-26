import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import recovery_gate
class RecoveryTests(unittest.TestCase):
 def test_only_next_registered_block(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);jobs=[{'key':str(i)} for i in range(192)];(p/'manifest.json').write_text(json.dumps({'jobs':jobs}))
   with patch.object(recovery_gate,'original_inspect',side_effect=[{'state':'blocked'},{'state':'blocked'}]) as f:
    r=recovery_gate.inspect(p,[]);self.assertEqual(r['state'],'blocked');self.assertEqual(f.call_args_list[1].args[1],jobs[4:8]);self.assertEqual(f.call_count,2)
 def test_waiting_is_not_pass(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'manifest.json').write_text(json.dumps({'jobs':list(range(8))}))
   with patch.object(recovery_gate,'original_inspect',side_effect=[{'state':'blocked'},{'state':'waiting'}]):self.assertEqual(recovery_gate.inspect(p,[])['state'],'waiting')
if __name__=='__main__':unittest.main()
