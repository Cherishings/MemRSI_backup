"""Offline regression tests. No model calls, workers, or experiments are launched."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from memory_ops import MemoryOps, FORMAT_REMINDER, guidance_format_error
from memory_policy import BASE


def response(data=None, *, name='submit_guidance', reason='tool_calls'):
    if data is None:
        data = {'guidance': 'Consult the outstanding user requirements.', 'uncertainty': 'History may be incomplete.'}
    return NS(content=None, tool_calls=[NS(name=name, arguments=data)], finish_reason=reason)


def empty():
    # Actual failing envelope from case-03-rep0, call 13 (no credentials/history).
    return NS(content=None, tool_calls=[], finish_reason='stop')


class FakeProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.format_repairs = 0
    async def chat(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return value


class GuidanceFormatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'memory').mkdir()
        (self.root/'memory/MEMORY.md').write_text('ORIGINAL_LONG_MEMORY')
        self.short = [{'role': 'user', 'content': 'ORIGINAL_SHORT_MEMORY'}]
    def ops(self, replies):
        self.provider = FakeProvider(replies)
        return MemoryOps(self.provider,self.root,self.root,BASE,'UNMODIFIED_TOOL_CONTRACT')
    def events(self):
        return [json.loads(x) for x in (self.root/'guidance-format-events.jsonl').read_text().splitlines()]

    async def test_valid_response_unchanged_and_no_extra_call(self):
        result = await self.ops([response()]).guide(self.short,'Continue.')
        self.assertIn('Consult the outstanding', result)
        self.assertEqual(len(self.provider.requests),1)
        self.assertEqual(self.provider.format_repairs,0)
        self.assertIsNone(self.events()[0]['error_code'])

    async def test_actual_empty_reply_is_repaired_once_without_new_evidence(self):
        await self.ops([empty(),response()]).guide(self.short,'Continue.')
        a,b=self.provider.requests
        self.assertEqual(b['messages'][:-1],a['messages'])
        self.assertEqual(b['messages'][-1]['content'],FORMAT_REMINDER)
        self.assertEqual(b['tools'],a['tools'])
        self.assertEqual(b['tool_choice'],'required')
        self.assertEqual(self.provider.format_repairs,1)
        self.assertEqual([x['status'] for x in self.events()],['rejected','accepted'])
        self.assertEqual(self.events()[0]['error_code'],'missing_tool_call')
        self.assertEqual((self.root/'memory/MEMORY.md').read_text(),'ORIGINAL_LONG_MEMORY')
        self.assertEqual(self.short,[{'role':'user','content':'ORIGINAL_SHORT_MEMORY'}])
        record=json.loads((self.root/'guidance-events.jsonl').read_text())
        self.assertTrue(record['format_repaired'])

    async def test_repeated_empty_is_failure_not_fabricated_success(self):
        with self.assertRaisesRegex(RuntimeError,'guidance_protocol_failure'):
            await self.ops([empty(),empty(),response()]).guide(self.short,'Continue.')
        self.assertEqual(len(self.provider.requests),2)
        self.assertFalse(self.events()[-1]['retry_scheduled'])
        self.assertFalse((self.root/'guidance-events.jsonl').exists())

    async def test_wrong_action_tool_never_becomes_guidance(self):
        bad=response({'skill':'finish','reason':'done'},name='report_action')
        with self.assertRaisesRegex(RuntimeError,'guidance_protocol_failure'):
            await self.ops([bad,bad]).guide(self.short,'Continue.')
        self.assertEqual(self.events()[0]['error_code'],'wrong_tool_name')

    async def test_transport_failure_does_not_get_format_retry(self):
        with self.assertRaisesRegex(RuntimeError,'provider_error'):
            await self.ops([RuntimeError('provider_error')]).guide(self.short,'Continue.')
        self.assertEqual(len(self.provider.requests),1)
        self.assertEqual(self.provider.format_repairs,0)

    async def test_repair_obeys_existing_call_budget(self):
        with self.assertRaisesRegex(RuntimeError,'agent_call_budget_exhausted'):
            await self.ops([empty(),RuntimeError('agent_call_budget_exhausted')]).guide(self.short,'Continue.')
        self.assertFalse((self.root/'guidance-events.jsonl').exists())
        self.assertEqual(len(self.provider.requests),2)

    async def test_plain_text_is_not_parsed_into_guidance(self):
        prose=empty();prose.content='{"guidance":"finish","uncertainty":""}'
        with self.assertRaisesRegex(RuntimeError,'guidance_protocol_failure'):
            await self.ops([prose,prose]).guide(self.short,'Continue.')

    def test_rejects_malformed_arguments_and_incomplete_responses(self):
        invalid=[('invalid_fields',response('{}')),
            ('invalid_fields',response({'guidance':'x'})),
            ('invalid_fields',response({'guidance':'x','uncertainty':'','extra':True})),
            ('invalid_field_types',response({'guidance':None,'uncertainty':''})),
            ('empty_guidance',response({'guidance':'  ','uncertainty':''})),
            ('guidance_too_long',response({'guidance':'x'*6001,'uncertainty':''})),
            ('incomplete_response',response(reason='length'))]
        for code,item in invalid:
            with self.subTest(code=code):self.assertEqual(guidance_format_error(item),code)
        many=response();many.tool_calls*=2
        self.assertEqual(guidance_format_error(many),'multiple_tool_calls')
        self.assertIsNone(guidance_format_error(response({'guidance':'x'*6000,'uncertainty':''})))

if __name__=='__main__':unittest.main()
