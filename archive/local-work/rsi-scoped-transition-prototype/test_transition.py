import unittest, copy
from transition import apply_receipt, is_complete
class Tests(unittest.TestCase):
 def setUp(self):
  self.state={(x,'service'):{'required':['part_one','part_two'],'completed':['part_one']} for x in ['entity_a','entity_b','entity_c','entity_e']}
  self.d={'id':'decision_e','entity':'entity_e','obligation':'service'}
  self.r={'decision_id':'decision_e','entity':'entity_e','obligation':'service','completed_components':['part_two']}
 def test_scope_preservation(self):
  out=apply_receipt(self.state,self.d,self.r)
  self.assertTrue(is_complete(out[('entity_e','service')]))
  for x in ['entity_a','entity_b','entity_c']:
   self.assertEqual(out[(x,'service')],self.state[(x,'service')]);self.assertFalse(is_complete(out[(x,'service')]))
 def test_partial_is_not_complete(self):
  self.r['completed_components']=['part_one'];self.assertFalse(is_complete(apply_receipt(self.state,self.d,self.r)[('entity_e','service')]))
 def test_duplicate_is_idempotent(self):
  out=apply_receipt(self.state,self.d,self.r);self.assertEqual(out,apply_receipt(out,self.d,self.r))
 def test_wrong_correlation_atomic(self):
  before=copy.deepcopy(self.state);self.r['decision_id']='different'
  with self.assertRaises(ValueError):apply_receipt(self.state,self.d,self.r)
  self.assertEqual(before,self.state)
 def test_wrong_entity(self):
  self.r['entity']='entity_a'
  with self.assertRaises(ValueError):apply_receipt(self.state,self.d,self.r)
 def test_no_scope_expansion(self):
  self.r['completed_components']=['unrequested']
  with self.assertRaises(ValueError):apply_receipt(self.state,self.d,self.r)
 def test_other_obligation_same_entity(self):
  self.state[('entity_e','other')]={'required':['part_two'],'completed':[]}
  out=apply_receipt(self.state,self.d,self.r);self.assertEqual(out[('entity_e','other')],self.state[('entity_e','other')])
 def test_no_extra_fields(self):
  self.r['complete_everything']=True
  with self.assertRaises(ValueError):apply_receipt(self.state,self.d,self.r)
if __name__=='__main__':unittest.main()
