import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import replay


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, selected):
        calls=[]
        class FakeAgent:
            def __init__(self,*args,**kwargs):
                self.provider=types.SimpleNamespace(calls=1);self.policy_hash='test'
            async def replay_observe(self,text,decision_record=None):calls.append(('prefix',text,decision_record))
            async def observe_only(self,text,facts):calls.append(('observe',text))
            async def rollover(self):calls.append(('rollover',))
            async def turn(self,text,facts,decision=False):
                calls.append(('choose',text));return {'skill':selected,'reason':'test'}
            async def close(self):pass
        f={'source':'saved','source_result_sha256':'test','case':'delay','history':'one_first','jobs':12,
           'events':[{'id':1,'text':'original mission'}, {'id':2,'text':'Continue','decision_requested':True},
                     {'id':3,'text':'FEEDBACK_FOR_OTHER_ACTION'}, {'id':4,'text':'Continue','decision_requested':True}],
           'decisions':{2:{'expected':'serve_table_one','choice':{'skill':'serve_table_two'},'stage':'return_1'},
                        4:{'expected':'finish','choice':{'skill':'finish'},'stage':'finish'}},
           'rollovers_after':[],'checkpoint_ids':[2,4],'planned_checkpoints':3,'source_status':'decision_failure'}
        with tempfile.TemporaryDirectory() as temp, patch.object(replay,'fixture',return_value=f), \
             patch.dict(sys.modules,{'agent_adapter':types.SimpleNamespace(Agent=FakeAgent)}):
            result=await replay.evaluate('saved',Path(temp)/'result','policy')
        return result,calls

    async def test_wrong_action_stops_before_other_actions_feedback(self):
        r,calls=await self.execute('finish')
        self.assertEqual(r['status'],'decision_failure')
        self.assertFalse(any('FEEDBACK_FOR_OTHER_ACTION' in str(c) for c in calls))

    async def test_correct_different_action_has_no_observed_suffix(self):
        r,calls=await self.execute('serve_table_one')
        self.assertEqual(r['correct'],1)
        self.assertEqual(r['status'],'replay_suffix_unavailable')
        self.assertFalse(r['passed'])
        self.assertFalse(any('FEEDBACK_FOR_OTHER_ACTION' in str(c) for c in calls))
        self.assertEqual(r['original_planned_checkpoints'],3)
        self.assertEqual(r['observed'],1)

if __name__=='__main__':unittest.main()
