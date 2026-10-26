import copy,itertools,json,unittest
from process_compiler import CATALOG,compile_edit,combinations
class Tests(unittest.TestCase):
 def setUp(self):
  self.parent={'schema':1,**{k:json.dumps({'kind':'procedure_'+k+'_v2','procedure':'Fixed parent procedure.'}) for k in CATALOG}}
  self.choice={k:next(iter(v)) for k,v in CATALOG.items()}
 def test_exhaustive_finite_outputs_and_exact_ablations(self):
  original=copy.deepcopy(self.parent);seen=set()
  for g,u in itertools.product(*[list(v) for v in CATALOG.values()]):
   choice={'guidance':g,'update':u};arms=combinations(self.parent,choice)
   for k in CATALOG:
    body=json.loads(arms['joint'][k])['procedure']
    self.assertEqual(body,'Fixed parent procedure.\n'+CATALOG[k][choice[k]])
   self.assertEqual(arms['Gedit']['update'],self.parent['update'])
   self.assertEqual(arms['Uedit']['guidance'],self.parent['guidance'])
   seen.add(json.dumps(arms['joint'],sort_keys=True))
  self.assertEqual(len(seen),4);self.assertEqual(self.parent,original)
 def test_open_text_and_additional_channels_rejected(self):
  for bad in [dict(self.choice,rationale='Add a tool'),dict(self.choice,guidance='cite only top-level keys'),dict(self.choice,guidance={'operation':'x'}),{'guidance':self.choice['guidance']}]:
   with self.assertRaises(ValueError):compile_edit(self.parent,bad)
 def test_atomic_length_failure(self):
  p=copy.deepcopy(self.parent);p['update']=json.dumps({'kind':'procedure_update_v2','procedure':'x'*4096});original=copy.deepcopy(p)
  with self.assertRaises(ValueError):compile_edit(p,self.choice)
  self.assertEqual(p,original)
 def test_no_schema_or_tool_output_in_catalog(self):
  for operations in CATALOG.values():
   for text in operations.values():
    for name in ['basis_ids','report_advice','required field','output schema','80 words','1200 characters']:
     self.assertNotIn(name,text)
if __name__=='__main__':unittest.main()
