import json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from advisor import Advisor, payload, validate

def response(d):
    return NS(finish_reason='tool_calls', tool_calls=[NS(name='report_advice', arguments=d)])

class ContractTests(unittest.TestCase):
    def test_projection_preserves_tools_excludes_metadata(self):
        p = payload('m', 'h', [{'role':'assistant','content':'c','tool_calls':[{'id':'a'}],'expected_private':'NO'}], 'q', 'api')
        self.assertEqual(p['evidence']['short:0']['tool_calls'], [{'id':'a'}])
        self.assertNotIn('expected_private', p['evidence']['short:0'])
        self.assertEqual(p['execution_api'], 'api')
    def test_missing_api_rejected(self):
        with self.assertRaises(ValueError): payload('', '', [], '', '')
    def test_unknown_citation_rejected(self):
        with self.assertRaises(ValueError): validate(response({'recommendation':'x','basis_ids':['unknown'],'uncertainty':''}), {'current':'q'})
    def test_uncited_advice_rejected(self):
        with self.assertRaises(ValueError): validate(response({'recommendation':'x','basis_ids':[],'uncertainty':''}), {'current':'q'})
    def test_abstention_preserved(self):
        d={'recommendation':'','basis_ids':[],'uncertainty':'Cannot resolve the reference'}
        self.assertEqual(validate(response(d), {}), d)

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_call_no_execution_or_memory_mutation(self):
        class Fake:
            def __init__(self): self.requests=[];self.events=[]
            async def chat(self, **kw):
                self.requests.append(kw)
                return response({'recommendation':'Inspect the public state','basis_ids':['current'],'uncertainty':'Outcome is unknown'})
            def _append(self,*args): self.events.append(args)
        with tempfile.TemporaryDirectory() as t:
            m=Path(t)/'memory';m.mkdir();f=m/'MEMORY.md';f.write_text('original')
            p=Fake();text=await Advisor(p,t,'public API').guide([], 'current request')
            self.assertEqual(len(p.requests),1)
            self.assertEqual(f.read_text(),'original')
            self.assertEqual([x['function']['name'] for x in p.requests[0]['tools']],['report_advice'])
            self.assertIn('public API',p.requests[0]['messages'][1]['content'])
            self.assertIn('may reject',text)
if __name__=='__main__': unittest.main()
