import copy,json,tempfile,unittest,hashlib
from pathlib import Path
from prepared import load,reject_duplicate
class PreparedTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name)
  self.req=json.loads((Path(__file__).parent.parent/'rsi-transition-feedback/full-request.json').read_text());self.data=json.loads(self.req['messages'][1]['content'])
  self.schema=self.req['tools'][0]['function']['parameters'];self.save()
 def tearDown(self):self.tmp.cleanup()
 def save(self):
  (self.r/'full-request.json').write_text(json.dumps(self.req));(self.r/'candidate-denylist.json').write_text(json.dumps({'joint_sha256':['old']}))
  sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
  (self.r/'prepared-registration.json').write_text(json.dumps({'request_sha256':sha(self.r/'full-request.json'),'denylist_sha256':sha(self.r/'candidate-denylist.json'),'input_tokens':49016}))
 def get(self,**kw):return load(self.r,kw.get('parent',self.data['parent']),kw.get('schema',self.schema),kw.get('runtime',self.data['existing_runtime_contract']),kw.get('count',lambda m,t:49016))
 def test_exact_payload(self):self.assertEqual(self.get()[0],self.req)
 def test_parent_schema_runtime_rejected(self):
  for field in ['parent','schema','runtime']:
   with self.subTest(field=field),self.assertRaises(ValueError):self.get(**{field:{}})
 def test_hash_rejected(self):
  with (self.r/'full-request.json').open('a') as f:f.write(' ')
  with self.assertRaises(ValueError):self.get()
 def test_budget_rejected(self):
  for n in [49017,49153]:
   with self.assertRaises(ValueError):self.get(count=lambda m,t:n)
 def test_split_rejected(self):
  self.data['validation_feedback_provided']=True;self.req['messages'][1]['content']=json.dumps(self.data);self.save()
  with self.assertRaises(ValueError):self.get()
 def test_denylist_tamper_rejected(self):
  (self.r/'candidate-denylist.json').write_text('{}')
  with self.assertRaises(ValueError):self.get()
 def test_duplicate_rejected(self):
  with self.assertRaises(ValueError):reject_duplicate({'joint':{}},['old'],lambda p:'old')
  reject_duplicate({'joint':{}},['old'],lambda p:'new')

class DispatchTests(unittest.IsolatedAsyncioTestCase):
 async def test_exact_dispatch_and_no_resample(self):
  import learn
  from types import SimpleNamespace
  captured=[]
  class Provider:
   def __init__(self,folder):self._client=self
   async def chat(self,**kwargs):
    captured.append(kwargs);raise RuntimeError('generation_output_limit')
   async def close(self):pass
  module=SimpleNamespace(MODEL='offline',Provider=Provider)
  req=json.loads((Path(__file__).parent.parent/'rsi-transition-feedback/full-request.json').read_text())
  with tempfile.TemporaryDirectory() as root:
   folder=Path(root)/'proposal'
   for _ in range(2):
    value,rejection=await learn.single_structured(folder,None,None,{},module,prepared=(req,{}))
    self.assertIsNone(value);self.assertEqual(rejection['code'],'generation_output_limit')
   self.assertEqual(len(captured),1)
   self.assertEqual(captured[0]['messages'],req['messages']);self.assertEqual(captured[0]['tools'],req['tools'])
