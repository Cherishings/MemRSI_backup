import unittest
from protocol import case,cases,contract
class ProtocolTests(unittest.TestCase):
 def test_same_present_different_past(self):
  for platform in ('twin','casa'):
   for gap in (4,8):
    a,b=case(platform,gap,False),case(platform,gap,True)
    self.assertNotEqual(a['steps'][0]['text'],b['steps'][0]['text'])
    self.assertEqual([s['text'] for s in a['steps'][1:]],[s['text'] for s in b['steps'][1:]])
    self.assertEqual([s['expected'] for s in a['steps'] if s['checkpoint']][:-1],list(reversed([s['expected'] for s in b['steps'] if s['checkpoint']][:-1])))
 def test_real_work_counts_and_three_probes(self):
  for platform in ('twin','casa'):
   for p in cases(platform):
    self.assertEqual(sum('work_order' in s for s in p['steps']),p['gap'])
    self.assertEqual(sum(s['checkpoint'] for s in p['steps']),3)
    self.assertTrue(all(s['text']=='Continue.' for s in p['steps'] if s['checkpoint']))
    self.assertTrue(all(s['expected'] in contract(platform)[1] for s in p['steps']))
 def test_earlier_progress_never_omitted(self):
  for platform in ('twin','casa'):
   for p in cases(platform):
    self.assertEqual(p['steps'][0]['expected'],'station_A')
    self.assertEqual(p['steps'][-1]['expected'],'finish')
if __name__=='__main__':unittest.main()
