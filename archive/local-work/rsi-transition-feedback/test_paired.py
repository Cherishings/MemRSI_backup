import unittest,json,copy
from pathlib import Path
from paired import build_view,pack_memories,unpack_one
class PairedTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.data=json.loads((Path(__file__).parent/'training-transitions.json').read_text())
 def test_alignment(self):
  v=build_view(self.data);self.assertEqual(len(v['paired']),8)
  for g in v['paired']:
   self.assertEqual(len(g['details']),4);self.assertEqual({d['event'] for d in g['details']},{g['shared_event']})
 def test_roundtrip(self):
  v=build_view(self.data);p=pack_memories(v)
  for g,h in zip(v['paired']+[v['diagnostic']],p['paired']+[p['diagnostic']]):
   for d,e in zip(g['details'],h['details']):
    for n,k in d['refs'].items():self.assertEqual(v['shared_text'][k],unpack_one(p['memory_pool'],e['refs'][n]))
 def test_diagnostic_full(self):
  v=build_view(self.data);d=v['diagnostic']['details'];self.assertEqual(len(d),1);self.assertEqual(d[0]['archive'],'rollover-13')
  msgs=d[0]['public_messages'];self.assertTrue(any('"native_task_complete": true' in m.get('content','') for m in msgs['messages']))
 def test_missing_arm(self):
  d=copy.deepcopy(self.data);d['rows'].pop()
  with self.assertRaises(ValueError):build_view(d)
if __name__=='__main__':unittest.main()
