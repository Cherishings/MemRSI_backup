import asyncio,copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from delta_memory import EMPTY,apply,encode,decode,DeltaStore,sources_for

def edit(section='requirements',key='mission',revision=0,text='User requires the original order.',source='e0',quote='original order',**kw):
 return dict(section=section,id=key,op='set',expected_revision=revision,text=text,status='active',links=[],evidence=[source],**kw)
class TransactionTests(unittest.TestCase):
 def test_progress_does_not_rewrite_requirement(self):
  src=sources_for([{'content':'User requires original order.'},{'content':'one component placed'}],EMPTY)
  old=apply(EMPTY,{'edits':[edit()]},src)
  e=edit(section='progress',key='placement',text='one component placed',source='e1',quote='one component placed');e['links']=['mission']
  new=apply(old,{'edits':[e]},src)
  self.assertEqual(new['requirements'],old['requirements']);self.assertEqual(decode(encode(new)),new)
 def test_revision_and_quote_verified_atomically(self):
  src=sources_for([{'content':'original order'}],EMPTY);old=apply(EMPTY,{'edits':[edit()]},src);snapshot=copy.deepcopy(old)
  with self.assertRaisesRegex(ValueError,'stale_revision'):apply(old,{'edits':[edit()]},src)
  with self.assertRaisesRegex(ValueError,'unknown_id'):apply(old,{'edits':[edit(revision=1,source='imaginary authority')]},src)
  self.assertEqual(old,snapshot)
 def test_real_user_revision_is_allowed_no_hard_order_guard(self):
  src=sources_for([{'content':'original order'},{'content':'replace the previous order'}],EMPTY)
  old=apply(EMPTY,{'edits':[edit()]},src)
  new=apply(old,{'edits':[edit(revision=1,text='New order',source='e1',quote='replace the previous order')]},src)
  self.assertEqual(new['requirements']['mission']['text'],'New order')
 def test_model_can_forget_records_but_not_break_links(self):
  src=sources_for([{'content':'original order'}],EMPTY);e=edit();old=apply(EMPTY,{'edits':[e]},src)
  e.update(op='delete',expected_revision=1)
  self.assertEqual(apply(old,{'edits':[e]},src),EMPTY)
  x=edit(section='progress',key='p');x['links']=['missing']
  with self.assertRaisesRegex(ValueError,'dangling_link'):apply(EMPTY,{'edits':[x]},src)

class StoreTests(unittest.IsolatedAsyncioTestCase):
 async def test_failed_delta_does_not_commit_anything(self):
  class Provider:
   format_repairs=0
   async def chat(self,**kwargs):return SimpleNamespace(finish_reason='stop',tool_calls=[])
  with tempfile.TemporaryDirectory() as tmp:
   store=DeltaStore(Path(tmp),1024,lambda *a:None,{'update':json.dumps({'procedure':'generic'})})
   store.memory_file.write_text(encode(EMPTY));store.history_file.write_text('retained until commit')
   self.assertFalse(await store.consolidate([{'content':'feedback'}],Provider(),'model'))
   self.assertEqual(store.history_file.read_text(),'retained until commit');self.assertEqual(decode(store.read_long_term()),EMPTY)
 async def test_commit_stays_under_shared_capacity(self):
  class Provider:
   format_repairs=0
   async def chat(self,**kwargs):return SimpleNamespace(finish_reason='tool_calls',tool_calls=[SimpleNamespace(name='apply_memory_delta',arguments={'edits':[edit()]})])
  with tempfile.TemporaryDirectory() as tmp:
   store=DeltaStore(Path(tmp),1024,lambda *a:None,{'update':json.dumps({'procedure':'generic'})})
   self.assertTrue(await store.consolidate([{'content':'original order'}],Provider(),'model'))
   self.assertEqual(decode(store.read_long_term())['requirements']['mission']['revision'],1)

if __name__=='__main__':unittest.main()
