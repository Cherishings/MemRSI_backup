import tempfile,json,unittest
from pathlib import Path
from unittest.mock import patch
from targeted_requests import cached_structured
from replay import dump
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_resume_existing_failed_request_no_reset_and_cache_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);dump(p/'calls.json',{'calls':1});(p/'model-errors.jsonl').write_text('{"http_status":502}\n');calls=[]
   async def run(dest,*a):calls.append(dest.name);dest.mkdir();dump(dest/'value.json',{'guidance':'valid'});return {'guidance':'valid'}
   with patch('targeted_requests.structured',run):
    result=await cached_structured(p,'s',{}, {},lambda:None);await cached_structured(p,'s',{}, {},lambda:None)
   self.assertEqual(calls,['attempt-02']);self.assertTrue((p/'attempt-01/calls.json').exists())
 async def test_three_failed_attempts_are_exhausted_not_restarted(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)
   for i in range(1,4):
    d=p/f'attempt-{i:02d}';d.mkdir();(d/'model-errors.jsonl').write_text('{}\n')
   with patch('targeted_requests.structured') as model:
    with self.assertRaisesRegex(RuntimeError,'exhausted'):await cached_structured(p,'s',{}, {},lambda:None)
    model.assert_not_called()
 async def test_changed_payload_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);dump(p/'request-identity.json',{'sha256':'other'})
   with self.assertRaisesRegex(RuntimeError,'changed'):await cached_structured(p,'s',{}, {},lambda:None)
if __name__=='__main__':unittest.main()
