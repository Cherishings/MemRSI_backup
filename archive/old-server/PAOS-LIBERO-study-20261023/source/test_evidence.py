import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from execution_contract import receipt,enrich_history
from portable_metrics import rate,validate,information_pair,summarize,learning_gain
from stress_protocol import protocol,CASES
from memory_policy import choose_smallest

class EvidenceTests(unittest.TestCase):
    def test_partial_is_not_completed_and_no_private_mission_state(self):
        x={'success':True,'native_task_complete':False,'stop_after_one':True,'after':{'scene_observation':{'objects':{}}}}
        d=receipt('serve_table_one',x)
        self.assertFalse(d['native_task_complete']);self.assertEqual(d['execution_scope'],'partial_until_one_placement')
        self.assertNotIn('pending',json.dumps(d));self.assertNotIn('expected',json.dumps(d))
    def test_history_receipts_are_aligned_not_guessed(self):
        event={'id':2,'text':'Execution feedback: '+json.dumps({'skill':'one','scene_observation':{'x':1}})}
        x={'skill':'one','result':{'success':True,'native_task_complete':True,'after':{'scene_observation':{'x':1}}}}
        new,ids=enrich_history([event],[x]);self.assertEqual(ids,[2]);self.assertNotIn('native_task_complete',event['text'])
        self.assertTrue(json.loads(new[0]['text'].split(': ',1)[1])['native_task_complete'])
        x['skill']='two'
        with self.assertRaises(ValueError):enrich_history([event],[x])
    def test_all_history_pairs_same_physical_prefix_but_different_required_choice(self):
        for case in CASES:
            for jobs in (16,32):
                a,b=[protocol(case,h,jobs) for h in ('one_first','two_first')]
                self.assertEqual(a['pre_actions'],b['pre_actions']);self.assertEqual(a['partial_initial'],b['partial_initial'])
                self.assertNotEqual(a['expected_remaining'][0],b['expected_remaining'][0])
                if case!='delay':self.assertTrue(a['partial_initial'])
    def test_format_repair_alone_cannot_promote_memory_rules(self):
        scores={k:{'passed':[False,True],'decision_failure':[False,False],'tokens':100} for k in ['old','update_only','guidance_only','joint']}
        scores['joint']['passed']=[True,True]
        self.assertEqual(choose_smallest(scores),'old')
    def test_zero_coverage_is_undefined_not_zero_accuracy(self):
        self.assertIsNone(rate(0,0)['value'])
        r=dict(schema='mission-eval-v0.1',environment='RoboTwin',status='execution_failure',case='resume',history='one_first',length_jobs=32,
            planned_checkpoints=3,reached_checkpoints=0,answered_checkpoints=0,correct_checkpoints=0,
            physical_attempts=1,physical_successes=0,valid_trajectory=False,error_forms=[])
        result=summarize([r],1);self.assertIsNone(result['correct_at_reached']['value']);self.assertEqual(result['checkpoint_coverage']['value'],0)
        r['environment']='RoboDojo';self.assertEqual(summarize([r],1),result)
    def test_learning_gain_keeps_regressions_and_unmatched(self):
        base=dict(environment='LIBERO',case='resume',history='one_first',length_jobs=16,init=0,variant=0,status='success',valid_trajectory=True)
        a=[base,dict(base,history='two_first',valid_trajectory=False,status='decision_failure')]
        b=[dict(base,valid_trajectory=False,status='decision_failure'),dict(a[1],valid_trajectory=True,status='success')]
        result=learning_gain(a,b)
        self.assertEqual((result['improved'],result['regressed'],result['success_rate_difference']),(1,1,0))
        self.assertEqual(learning_gain(a,b[:1])['before_unmatched'],1)
    def test_fixed_answer_cannot_pass_history_pair(self):
        snap={'current_input_sha256':'x','station_state_sha256':{'s':'y'},'action_contract_sha256':'z'}
        a={'recovery_snapshot':dict(snap,expected_first_private='A'),'checkpoint_choices':[{'correct':True}]}
        b={'recovery_snapshot':dict(snap,expected_first_private='B'),'checkpoint_choices':[{'correct':False}]}
        self.assertTrue(information_pair(a,b)['history_required']);self.assertFalse(information_pair(a,b)['paired_correct'])

class AdapterRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_neutral_retry_no_python_finish_choice_both_arms(self):
        from agent_adapter import Agent,COMMON_TOOLS
        from memory_policy import BASE
        for arm in ('native','memrsi'):
            with self.subTest(arm=arm),tempfile.TemporaryDirectory() as td:
                root=Path(td);p=root/'policy.json';p.write_text(json.dumps(BASE))
                with patch('model_provider.read_api_key',return_value='TEST'):
                    a=Agent(arm,root/'case'/arm,p if arm=='memrsi' else None)
                calls=[]
                async def process(message,**kw):
                    calls.append(message)
                    if len(calls)==2:await a.action.execute('finish','model submitted, not parsed from prose')
                    return 'All done.'
                try:
                    if a.ops:
                        async def guide(*args):return 'test guide'
                        a.ops.guide=guide
                        self.assertEqual(a.ops.action_contract,COMMON_TOOLS)
                    with patch.object(a.loop,'process_direct',process):out=await a.turn('Continue.',decision=True)
                    self.assertEqual(out['skill'],'finish');self.assertEqual(len(calls),2)
                    self.assertEqual(a.provider.format_repairs,1);self.assertNotIn('finish',calls[1])
                finally:await a.close()
