import unittest
from reliable_policy import reconnecting_client
class T(unittest.TestCase):
 def test_same_query_after_disconnect(self):
  calls=[];clients=[];waits=[]
  class C:
   def __init__(self,*a,**k):clients.append(self);self._ws=self
   def get_server_metadata(self):return {'paired_sampling':True}
   def close(self):pass
   def infer(self,q):
    calls.append(q.copy())
    if len(calls)==1:raise ConnectionError('dropped response')
    return {'actions':[1]}
  p=reconnecting_client(C,(OSError,),waits.append)('localhost',1)
  q={'_paired_sampling_seed':42,'state':[3]};self.assertEqual(p.infer(q),{'actions':[1]});self.assertEqual(calls,[q,q]);self.assertEqual(len(clients),2);self.assertEqual(waits,[2])
 def test_application_error_not_retried(self):
  class C:
   def __init__(self,*a):pass
   def get_server_metadata(self):return {}
   def infer(self,q):raise RuntimeError('invalid action')
  p=reconnecting_client(C,(OSError,),lambda _:self.fail())()
  with self.assertRaisesRegex(RuntimeError,'invalid action'):p.infer({'_paired_sampling_seed':1})
 def test_metadata_change_blocks(self):
  clients=[]
  class C:
   def __init__(self):clients.append(self);self._ws=self
   def get_server_metadata(self):return {'version':len(clients)}
   def close(self):pass
   def infer(self,q):raise ConnectionError()
  p=reconnecting_client(C,(OSError,),lambda _:None)()
  with self.assertRaisesRegex(RuntimeError,'metadata_changed'):p.infer({'_paired_sampling_seed':1})
unittest.main()
