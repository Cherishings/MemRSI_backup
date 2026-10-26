import asyncio,copy,unittest
from design_support import development_plan,contract_feedback,bounded_proposal
class Tests(unittest.TestCase):
 def setUp(self):
  self.sources=[{'id':x,'split':'development','sha256':'a'*64} for x in ['a','b']]
  self.rows=[dict(case=x,repeat=r,split='development',policy_sha256='p',technical_failure=False,correct=2,planned=2) for x in ['a','b'] for r in range(2)]
  self.parent={'guidance':'Alpha. Beta.','update':'Preserve task evidence.'}
  self.patch={'target':'guidance','anchor':'','replacement':'New evidence.', 'rationale':'Clarify relevance.'}
 def test_ceiling_skips_without_changing_gate(self):
  x=development_plan(self.sources,self.rows,'p');self.assertFalse(x['proposal_allowed']);self.assertFalse(x['selection_gate_changed'])
 def test_unsaturated_preserves_success_controls(self):
  self.rows[0]['correct']=1;x=development_plan(self.sources,self.rows,'p');self.assertTrue(x['proposal_allowed']);self.assertEqual(x['sources'],self.sources);self.assertEqual(x['pairs'],4)
 def test_no_formal(self):
  for field in ('sources','rows'):
   s=copy.deepcopy(self.sources);r=copy.deepcopy(self.rows);(s if field=='sources' else r)[0]['split']='test'
   with self.assertRaises(ValueError):development_plan(s,r,'p')
 def test_missing_duplicate_wrongparent_block(self):
  for r in (self.rows[:-1],self.rows+[self.rows[0]],[dict(x,policy_sha256='other') for x in self.rows]):
   with self.assertRaises(ValueError):development_plan(self.sources,r,'p')
 def test_technical_block(self):
  self.rows[0]['technical_failure']=True
  with self.assertRaises(ValueError):development_plan(self.sources,self.rows,'p')
 def test_full102_exact_length_feedback(self):
  p=dict(self.patch,replacement='x'*1398);e=contract_feedback(self.parent,p);self.assertIn({'field':'replacement','code':'max_characters','observed':1398,'limit':1200,'excess':198},e)
 def test_parent_final_limit(self):
  p={'guidance':'a'*1500,'update':'b'};e=contract_feedback(p,dict(self.patch,replacement='x'*101));self.assertTrue(any(x['code']=='final_operator_limit' and x['max_replacement_for_this_anchor']==99 for x in e))
 def test_no_patch_mutation(self):
  before=copy.deepcopy(self.patch);self.assertEqual(contract_feedback(self.parent,self.patch),[]);self.assertEqual(self.patch,before)
 def test_exact_anchor(self):
  e=contract_feedback(self.parent,dict(self.patch,anchor='X'));self.assertTrue(any(x['code']=='unique_exact_anchor_required' for x in e))
 def test_one_resubmission_max(self):
  calls=[];audit=[]
  async def req(feedback):calls.append(feedback);return dict(self.patch,replacement='x'*1398)
  self.assertIsNone(asyncio.run(bounded_proposal(req,self.parent,lambda p,x:x,audit)));self.assertEqual(len(calls),2);self.assertEqual(calls[1]['errors'][0]['excess'],198)
 def test_transport_not_retried(self):
  calls=[]
  async def req(feedback):calls.append(feedback);raise OSError('network')
  with self.assertRaises(OSError):asyncio.run(bounded_proposal(req,self.parent,lambda p,x:x,[]))
  self.assertEqual(len(calls),1)
 def test_original_validator_preserved(self):
  async def req(feedback):return self.patch
  def validate(p,x):raise ValueError('generic_screen_rejected')
  with self.assertRaisesRegex(ValueError,'generic_screen_rejected'):asyncio.run(bounded_proposal(req,self.parent,validate,[]))
if __name__=='__main__':unittest.main()
