import copy,hashlib,unittest
from render import render
class RenderTests(unittest.TestCase):
 def setUp(self):
  s='start'+('x'*2000)+'end';h=hashlib.sha256(s.encode()).hexdigest()
  self.d={'validation_read':False,'test_read':False,'blobs':{h:s},'rows':[{'key':['s',a,0,'p'],'status':'failure','transitions':[{'archive':'rollover-'+str(i),'last_received_event':i,'success':True,'refs':{n:h for n in ['memory-before.md','memory-after.md','messages-before.json','audit.json']}} for i in [2,1]]} for a in ['joint','parent']]}
 def test_deterministic_order(self):
  a=render(self.d);self.d['rows'].reverse()
  for r in self.d['rows']:r['transitions'].reverse()
  self.assertEqual(a,render(self.d))
 def test_score_independent_selection(self):
  a=render(self.d)
  for r in self.d['rows']:r.update(status='success',correct=99)
  b=render(self.d);self.assertEqual([r['details'] for r in a['rows']],[r['details'] for r in b['rows']])
 def test_omissions_explicit(self):
  a=render(self.d,100);self.assertEqual(a['coverage']['inventory_transitions'],4);self.assertEqual(a['coverage']['detailed_transitions'],2)
  self.assertGreater(a['coverage']['omitted_chars_in_selected_fields'],0)
  f=a['rows'][0]['details'][0]['fields']['memory-before.md'];self.assertTrue(f['text'].startswith('start'));self.assertTrue(f['text'].endswith('end'))
 def test_corruption_rejected(self):
  self.d['blobs'][next(iter(self.d['blobs']))]='bad'
  with self.assertRaises(ValueError):render(self.d)
 def test_wrong_scope(self):
  self.d['validation_read']=True
  with self.assertRaises(ValueError):render(self.d)
if __name__=='__main__':unittest.main()
