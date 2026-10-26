"""No processes launched; exercise continuation guard with file-shaped fixtures."""
import unittest
from pathlib import Path
from unittest.mock import patch
from schedule import predecessor_ready
class Tests(unittest.TestCase):
 def check(self,changes=None,exists_missing=False,alive=False):
  rows={'manifest.json':{'jobs':[{'key':'x'}]},'scheduler.json':{'identity':{'pid':10}},'relay-progress.json':{'phase':'launched'},'launched.json':{'workers':{'1':{'pid':11}}},'worker-gpu1.json':{'identity':{'pid':11},'phase':'completed'},'claims.json':{'x':{}},'result.json':{'status':'success'}}
  rows.update(changes or {})
  def read(p,default=None):return rows.get(p.name,default)
  def exists(p):return p.name=='result.json' and not exists_missing
  with patch('schedule.cap.file_sha',return_value='h'),patch('schedule.cap.read',side_effect=read),patch('schedule.cap.alive',return_value=alive),patch.object(Path,'exists',exists):
   return predecessor_ready(Path('/frozen'),{'predecessor_manifest_sha256':'h'})
 def test_complete(self):self.assertEqual(self.check(),(True,0))
 def test_missing_result_waits(self):self.assertEqual(self.check(exists_missing=True),(False,1))
 def test_live_scheduler_waits(self):self.assertEqual(self.check(alive=True),(False,0))
 def test_wrong_identity_blocks(self):
  with self.assertRaisesRegex(RuntimeError,'identity'):self.check({'worker-gpu1.json':{'identity':{'pid':99},'phase':'completed'}})
 def test_abnormal_exit_blocks(self):
  with self.assertRaisesRegex(RuntimeError,'abnormal'):self.check({'worker-gpu1.json':{'identity':{'pid':11},'phase':'trial'}})
 def test_technical_blocks(self):
  with self.assertRaisesRegex(RuntimeError,'technical'):self.check({'result.json':{'status':'technical_failure'}})
 def test_incomplete_relay_blocks(self):
  with self.assertRaisesRegex(RuntimeError,'scheduler_not_complete'):self.check({'relay-progress.json':{'phase':'waiting'}})
if __name__=='__main__':unittest.main()
