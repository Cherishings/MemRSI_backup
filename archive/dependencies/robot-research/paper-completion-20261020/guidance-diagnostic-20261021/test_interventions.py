"""Zero-network intervention checks, including genuine native constructors."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from interventions import agent_class, ARMS
from cap10_ops import checked_selection, fragments

def response(ids):
    return NS(finish_reason='tool_calls', tool_calls=[NS(name='select_memory_evidence', arguments={'ids': ids})])

class Provider:
    def __init__(self): self.logs=[]; self.format_repairs=0
    def _append(self, name, value): self.logs.append((name, value))

POLICY={'schema':1,'guidance':json.dumps({'kind':'procedure_guidance_v2','procedure':'Select up to five evidence fragment IDs for the acting agent.'}), 'update':'unchanged'}
class Fake:
    def __init__(self):
        self.provider=Provider(); self.history=[{'role':'user','content':'real previous instruction'}]
        self.rollovers=[]; self.writes={}; self.calls=[]
        async def guide(short,current):
            self.calls.append((copy.deepcopy(short),current)); return 'evidence'
        self.ops=NS(guide=guide, policy=copy.deepcopy(POLICY),provider=self.provider,
                    workspace='/tmp',output='/tmp',action_contract='frozen')
    def _write(self,name,value):self.writes[name]=value
    async def rollover(self):self.rollovers.append(True);self.history.clear()

class Tests(unittest.TestCase):
    def test_cap10_accepts_ten_verbatim(self):
        catalog=fragments({'long':'a\n'*11}); result=checked_selection(response(list(catalog)[:10]),catalog)
        self.assertEqual(len(result),10); self.assertEqual(''.join(x['text'] for x in result),'a\n'*10)
    def test_reject_eleven(self):
        c=fragments({'long':'a\n'*11});self.assertIsNone(checked_selection(response(list(c)),c))
    def test_reject_duplicate(self):
        c=fragments({'long':'a'});self.assertIsNone(checked_selection(response(['long:0']*2),c))
    def test_reject_invented(self):
        self.assertIsNone(checked_selection(response(['answer:0']),{}))
    def test_reject_partial(self):
        r=response([]);r.finish_reason='length';self.assertIsNone(checked_selection(r,{}))
    def test_lossless_windows(self):
        text='x'*1201+'\nhi';c=fragments({'short':text});self.assertEqual(''.join(v['text'] for v in c.values()),text)
    def test_cadence_matched_and_preserves_history(self):
        for arm in ('cadence2_full','cadence2_no_short'):
            a=agent_class(Fake,arm)();asyncio.run(a.rollover());self.assertTrue(a.history)
            asyncio.run(a.rollover());self.assertEqual(a.history,[]);self.assertEqual(len(a.rollovers),1)
            a.history=[{'content':'new'}];asyncio.run(a.rollover());self.assertTrue(a.history)
            self.assertEqual(a.actual_boundaries,1);self.assertEqual(a.requested_boundaries,3)
    def test_real_nonempty_short_contrast_without_actor_mutation(self):
        for arm,n in [('cadence2_full',1),('cadence2_no_short',0),('cap5_control',1)]:
            a=agent_class(Fake,arm)();before=copy.deepcopy(a.history)
            asyncio.run(a.ops.guide(a.history,'current task'))
            self.assertEqual(len(a.calls[0][0]),n);self.assertEqual(a.calls[0][1],'current task')
            self.assertEqual(a.history,before)
    def test_control_boundary_unchanged(self):
        a=agent_class(Fake,'cap5_control')();asyncio.run(a.rollover());self.assertFalse(a.history)
    def test_cap10_only_changes_cap_phrase(self):
        a=agent_class(Fake,'cap10')();p=a.ops.policy
        self.assertEqual(p['update'],POLICY['update']);self.assertEqual(POLICY['guidance'].count('five'),1)
        self.assertEqual(json.loads(p['guidance'])['procedure'],json.loads(POLICY['guidance'])['procedure'].replace('five','ten'))
    def test_cap10_prompt_schema_and_validator_agree(self):
        async def check():
            a=agent_class(Fake,'cap10')()
            with tempfile.TemporaryDirectory() as d:
                a.ops.workspace=Path(d); (Path(d)/'memory').mkdir();(Path(d)/'memory/MEMORY.md').write_text('a\n'*11)
                async def chat(**kw):
                    self.assertIn('up to ten',kw['messages'][0]['content'])
                    self.assertEqual(kw['tools'][0]['function']['parameters']['properties']['ids']['maxItems'],10)
                    return response(['long:'+str(i) for i in range(10)])
                a.provider.chat=chat
                result=await a.ops.guide([], 'current')
                self.assertEqual(len(json.loads(result.split('\n',2)[-1])),10)
        asyncio.run(check())
    def test_unregistered_arm_rejected(self):
        with self.assertRaises(ValueError):agent_class(Fake,'unknown')

if __name__=='__main__':unittest.main()
