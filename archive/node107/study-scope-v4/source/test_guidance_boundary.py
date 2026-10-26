"""A fallible guidance generator must not become an execution authority."""
import json
import tempfile
import unittest
from pathlib import Path
from memory_ops import MemoryOps
from memory_policy import BASE
from action_catalog import CATALOG, CONTRACT, action_parameters
from test_guidance_format import FakeProvider, response

class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_guidance_call_no_semantic_veto_or_second_judge(self):
        with tempfile.TemporaryDirectory() as d:
            p=FakeProvider([response({'guidance':'Begin the currently requested table and pause after one placement.',
                                     'uncertainty':'The low-level skill determines the placement sequence.'})])
            text=await MemoryOps(p,d,d,BASE,CONTRACT).guide([], 'Begin table B and pause after one placement.')
            self.assertIn('actor makes its own final choice',text)
            self.assertEqual(len(p.requests),1)
            self.assertEqual(p.requests[0]['tools'][0]['function']['name'],'submit_guidance')
            row=json.loads((Path(d)/'guidance-events.jsonl').read_text())
            self.assertFalse(row['runtime_semantic_veto'])

    async def test_guidance_does_not_write_memory_or_make_action(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'memory').mkdir();(root/'memory/MEMORY.md').write_text('Archived state.')
            p=FakeProvider([response({'guidance':'No outstanding work is recorded.','uncertainty':''})])
            await MemoryOps(p,d,d,BASE,CONTRACT).guide([], 'Continue.')
            self.assertEqual((root/'memory/MEMORY.md').read_text(),'Archived state.')
            self.assertNotIn('report_action',json.dumps(p.requests[0]['tools']))

    def test_catalog_not_scoring_or_pending_state(self):
        self.assertEqual(set(action_parameters()['properties']['skill']['enum']),set(CATALOG))
        for private in ('expected_private','final_order_private','alpha','beta','pending_tables'):
            self.assertNotIn(private,CONTRACT)

if __name__=='__main__':unittest.main()
