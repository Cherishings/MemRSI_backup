import asyncio,copy,fcntl,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from PhyAgentOS.providers.base import LLMResponse,ToolCallRequest
from model_provider import Provider
from network_wait import transient,WaitClock,paused_seconds

NET={'exception_type':'InternalServerError','http_status':502,'stage':'http_connect','upstream_error_type':'ReadTimeout','output_started':False,'retryable':True}
class Tests(unittest.IsolatedAsyncioTestCase):
 async def make_run(self,root,failures=0):
  p=Provider(root/'trial',api_key='TEST_KEY');seen=[]
  async def complete(req):
   seen.append(copy.deepcopy(req))
   if len(seen)<=failures:p.last_transport_error=dict(NET);return LLMResponse(content='error',finish_reason='error')
   return LLMResponse(content=None,finish_reason='tool_calls',tool_calls=[ToolCallRequest('1','report_action',{'skill':'finish'})])
  return p,seen,complete
 async def test_outage_longer_than_old_retry_limit_reuses_request_and_delivers_action_once(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p,seen,complete=await self.make_run(root,7);lock=root/'lease';waits=[]
   async def sleep(seconds):
    # A network backoff must not retain the global inference lease.
    if seconds>=1:
     with lock.open('a') as f:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
     waits.append(seconds)
   with patch('model_provider.MODEL_LOCK_PATH',lock),patch('model_provider.probe',return_value=True),patch.object(p,'_complete',complete),patch('model_provider.asyncio.sleep',sleep):
    result=await p.chat(messages=[{'role':'user','content':'continue'}])
   self.assertEqual(result.tool_calls[0].arguments,{'skill':'finish'})
   self.assertEqual(len(seen),8);self.assertTrue(all(r==seen[0] for r in seen));self.assertEqual(p.calls,1)
   self.assertEqual(len(waits),7);self.assertEqual(p.wire_attempts,8)
   self.assertFalse(json.loads((root/'trial/transport-wait.json').read_text())['waiting'])
   errors=[json.loads(x) for x in (root/'trial/model-errors.jsonl').read_text().splitlines()]
   self.assertEqual(len(errors),7);self.assertTrue(all(e['network_wait'] for e in errors))
 async def test_offline_checks_do_not_spend_model_budget(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p,seen,complete=await self.make_run(root)
   with patch('model_provider.MODEL_LOCK_PATH',root/'lock'),patch('model_provider.probe',side_effect=[False]*8+[True]),patch.object(p,'_complete',complete),patch('model_provider.asyncio.sleep',new=AsyncMock()):
    await p.chat(messages=[{'role':'user','content':'continue'}])
   self.assertEqual(len(seen),1);self.assertEqual(p.calls,1);self.assertEqual(p.wire_attempts,1)
 async def test_cancel_while_offline_does_not_send_request(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p,seen,complete=await self.make_run(root)
   with patch('model_provider.probe',return_value=False),patch.object(p,'_complete',complete),patch('model_provider.asyncio.sleep',side_effect=asyncio.CancelledError):
    with self.assertRaises(asyncio.CancelledError):await p.chat(messages=[])
   self.assertEqual(p.calls,0);self.assertEqual(seen,[])
 async def test_real_format_error_does_not_get_infinite_network_retries(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p,seen,_=await self.make_run(root)
   async def bad(req):
    seen.append(req);p.last_transport_error={'http_status':502,'stage':'stream','upstream_error_type':'ValueError','output_started':True};return LLMResponse(content='bad',finish_reason='error')
   with patch('model_provider.MODEL_LOCK_PATH',root/'lock'),patch('model_provider.probe',return_value=True),patch.object(p,'_complete',bad):
    with self.assertRaisesRegex(RuntimeError,'provider_error'):await p.chat(messages=[])
   self.assertEqual(len(seen),1)
 def test_terminal_errors_not_network(self):
  self.assertTrue(transient(NET))
  self.assertTrue(transient({'exception_type':'APIConnectionError'}))
  for change in [{'http_status':401},{'http_status':429},{'code':'generation_output_limit'},{'upstream_error_type':'ValueError'}]:self.assertFalse(transient(dict(NET,**change)))
 def test_worker_timeout_excludes_network_wait_only(self):
  with tempfile.TemporaryDirectory() as d:
   clock=WaitClock(d)
   with patch('network_wait.time.monotonic',return_value=100):clock.begin('offline')
   self.assertEqual(paused_seconds(d,now=400),300)
   with patch('network_wait.time.monotonic',return_value=500):clock.end()
   self.assertEqual(paused_seconds(d,now=1000),400)
if __name__=='__main__':unittest.main()
