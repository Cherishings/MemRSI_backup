import json,unittest
import memory_policy,memory_design
class LoaderTests(unittest.TestCase):
 def pol(self,n):
  return {'schema':1,'guidance':json.dumps({'kind':'procedure_guidance_v2','procedure':'x'*n}),'update':json.dumps({'kind':'procedure_update_v2','procedure':'y'*n})}
 def test_registered_boundary(self):
  for n in [1600,1800,4096]:
   p=self.pol(n);self.assertEqual(memory_policy.validate(p),p);self.assertEqual(len(memory_design.update_instruction(p['update'])),n)
 def test_above_boundary(self):
  p=self.pol(4097)
  with self.assertRaises(ValueError):memory_policy.validate(p)
  with self.assertRaises(ValueError):memory_design.update_instruction(p['update'])
 def test_legacy_limit_kept(self):
  p={'schema':1,'guidance':'x'*1800,'update':''};self.assertEqual(memory_policy.validate(p),p)
  p['guidance']+='x'
  with self.assertRaises(ValueError):memory_policy.validate(p)
 def test_encoded_vs_body(self):
  p=self.pol(2000);p['guidance']=json.dumps({'kind':'procedure_guidance_v2','procedure':'证'*2000})
  self.assertGreater(len(p['guidance']),4096);self.assertEqual(memory_policy.validate(p),p)
if __name__=='__main__':unittest.main()
