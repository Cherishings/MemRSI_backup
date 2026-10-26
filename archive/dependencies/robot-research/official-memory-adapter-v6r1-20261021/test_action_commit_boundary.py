import asyncio
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent/'common'))
from action_commit_boundary import patch_loop
from PhyAgentOS.agent.loop import AgentLoop

class Call:
    def __init__(self, name='report_action', valid=True):
        self.name, self.arguments, self.id = name, {'valid': valid}, 'call-test'
    def to_openai_tool_call(self):
        return {'id': self.id, 'type': 'function',
                'function': {'name': self.name, 'arguments': '{}'}}

def response(calls=(), text='chosen action', finish='tool_calls'):
    return types.SimpleNamespace(content=text, tool_calls=list(calls),
        has_tool_calls=bool(calls), finish_reason=finish,
        reasoning_content=None, thinking_blocks=None)

class Context:
    def add_assistant_message(self, messages, content, tools=None, **kw):
        return messages+[dict(role='assistant',content=content,tool_calls=tools)]
    def add_tool_result(self, messages, id, name, result):
        return messages+[dict(role='tool',tool_call_id=id,name=name,content=result)]

class Fixture:
    def __init__(self, responses):
        self.responses=list(responses);self.calls=0;self.records=[];self.events=[]
        self.tools=self;self.provider=self;self.context=Context()
        self.max_iterations=40;self.context_window_tokens=12288;self.model='test'
        self._strip_think=lambda x:x;self.writes=0
    def get_definitions(self):return []
    async def chat_with_retry(self, **kwargs):
        self.calls+=1
        item=self.responses.pop(0)
        if isinstance(item,Exception):raise item
        return item
    async def execute(self,name,args):
        if name=='write_file':self.writes+=1;return 'saved'
        if not args['valid']:return 'rejected'
        if self.records:return 'already committed'
        self.records.append({'skill':'execute'});return 'committed; execution pending'
    def run(self):
        method=patch_loop(AgentLoop._run_agent_loop,lambda:len(self.records)==1,
                          lambda i,t:self.events.append((i,list(t))))
        return asyncio.run(method(self,[]))

class Tests(unittest.TestCase):
    def test_postcommit_generation_failure_never_requested(self):
        f=Fixture([response([Call()]),RuntimeError('generation_output_limit')])
        text,tools,messages=f.run()
        self.assertEqual(f.calls,1);self.assertEqual(len(f.records),1)
        self.assertEqual([m['role'] for m in messages],['assistant','tool'])
        self.assertEqual(messages[-1]['content'],'committed; execution pending')
        self.assertEqual(text,'chosen action')
    def test_invalid_action_can_be_corrected(self):
        f=Fixture([response([Call(valid=False)]),response([Call()])]);f.run()
        self.assertEqual(f.calls,2);self.assertEqual(len(f.events),1)
    def test_no_commit_retains_native_final_text(self):
        f=Fixture([response([Call(valid=False)]),response(text='unable',finish='stop')])
        self.assertEqual(f.run()[0],'unable');self.assertEqual(f.events,[])
    def test_tool_batch_records_all_receipts(self):
        f=Fixture([response([Call(),Call('write_file')])])
        messages=f.run()[2];self.assertEqual(len(messages),3)
        self.assertEqual(f.writes,1);self.assertEqual(f.calls,1)
    def test_duplicate_action_does_not_double_dispatch(self):
        f=Fixture([response([Call(),Call()])]);f.run()
        self.assertEqual(len(f.records),1);self.assertEqual(f.calls,1)
    def test_precommit_failure_propagates(self):
        f=Fixture([RuntimeError('generation_output_limit')])
        with self.assertRaisesRegex(RuntimeError,'generation_output_limit'):f.run()
        self.assertEqual(f.records,[])
    def test_unrecognized_loop_rejected(self):
        async def other(self):return None
        with self.assertRaisesRegex(RuntimeError,'unrecognized_native_actor_loop'):
            patch_loop(other,lambda:False,lambda *args:None)
    def test_no_synthetic_assistant_after_tool(self):
        f=Fixture([response([Call()],text=None)])
        text,_,messages=f.run();self.assertEqual(text,'')
        self.assertEqual(len([m for m in messages if m['role']=='assistant']),1)
        self.assertIsNone(messages[0]['content'])

if __name__=='__main__':unittest.main()
