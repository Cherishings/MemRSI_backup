import unittest,tempfile,json,hashlib
from pathlib import Path
from transitions import build
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.f=self.root/'learning/training';self.f.mkdir(parents=True);self.rows=[]
  for i in range(32):
   p=self.f/'replays'/str(i);p.mkdir(parents=True)
   r={'source_id':str(i),'arm':'joint','repeat':0,'policy_sha256':'policy','output':str(p),'status':'source_error_corrected' if i%2 else 'decision_failure'};self.rows.append(r)
   (p/'result.json').write_text(json.dumps({'policy_sha256':'policy'}))
   a=p/'rollover-1';a.mkdir()
   for n,t in [('memory-before.md','pending'),('memory-after.md','pending'),('messages-before.json','[]')]: (a/n).write_text(t)
   h=hashlib.sha256(b'pending').hexdigest();(a/'audit.json').write_text(json.dumps({'memory_before_sha256':h,'memory_after_sha256':h,'policy_sha256':'policy','success':True}))
  self.save()
 def tearDown(self):self.t.cleanup()
 def save(self):
  (self.f/'rows.json').write_text(json.dumps(self.rows));(self.f/'manifest.json').write_text(json.dumps({'schedule':self.rows}))
 def test_all_rows_and_lossless_dedup(self):
  x=build(self.root);self.assertEqual(len(x['rows']),32);self.assertEqual(sum(len(r['transitions']) for r in x['rows']),32)
  ref=x['rows'][0]['transitions'][0]['refs']['memory-before.md'];self.assertEqual(x['blobs'][ref],'pending');self.assertEqual(len({r['status'] for r in x['rows']}),2)
 def test_incomplete(self):
  self.rows.pop();self.save()
  with self.assertRaises(ValueError):build(self.root)
 def test_duplicate(self):
  self.rows[-1]=self.rows[0];self.save()
  with self.assertRaises(ValueError):build(self.root)
 def test_nontraining(self):
  self.rows[0]['output']=str(self.root/'validation');self.save()
  with self.assertRaises(ValueError):build(self.root)
 def test_symlink_escape(self):
  p=self.f/'replays/0/rollover-1/memory-before.md';p.unlink();target=self.root/'secret';target.write_text('hidden');p.symlink_to(target)
  with self.assertRaises(ValueError):build(self.root)
 def test_tampered_memory(self):
  (self.f/'replays/0/rollover-1/memory-after.md').write_text('changed')
  with self.assertRaises(ValueError):build(self.root)
 def test_policy_mismatch(self):
  (self.f/'replays/0/result.json').write_text('{"policy_sha256":"wrong"}')
  with self.assertRaises(ValueError):build(self.root)
if __name__=='__main__':unittest.main()
