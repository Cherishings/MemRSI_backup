"""Queue integrity tests; fake skills are not research results."""
import asyncio
from collections import defaultdict
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from physical_queue import schedule, history_pair_audit, PHYSICAL_FILES
from physical_runner import wait_for_policy
from memory_policy import BASE
import physical_queue
from stress_protocol import protocol, CASES
import stress_workflow as workflow


class FakeWorld:
    fail_kitchen = False
    def __init__(self, out, port, init, order):
        self.steps, self.out = 10, out
        (out / 'physical').mkdir(parents=True)
        (out / 'physical/initial.json').write_text(json.dumps({'instruction': 'native skill test stub'}))
        self.initial = self.send('observe')
    def send(self, op, stop_after_one=False):
        if op == 'observe':
            return {'scene_observation': {'objects': {'marker': self.steps}},
                    'steps': self.steps, 'state_sha256': str(self.steps)}
        self.steps += 10
        ok = not (self.fail_kitchen and self.out.name.startswith('order-'))
        return {'success': ok, 'native_task_complete': ok and not stop_after_one, 'stop_after_one':stop_after_one, 'after': self.send('observe')}
    def close(self):
        pass


class PhysicalQueueTests(unittest.TestCase):
    def test_all_arms_share_each_physical_scenario_and_fresh_horizon(self):
        rows=schedule()
        self.assertEqual(len(rows),48)
        self.assertEqual(len({r['trial_id'] for r in rows}),48)
        by_scenario=defaultdict(list)
        for row in rows:by_scenario[row['scenario_id']].append(row)
        self.assertEqual(len(by_scenario),16)
        for members in by_scenario.values():
            self.assertEqual({r['arm'] for r in members},{'native','memrsi_fixed','memrsi_evolved'})
            for key in ('init','variant','history','jobs','case'):
                self.assertEqual(len({r[key] for r in members}),1)
            self.assertIn(members[0]['jobs'],(16,32))
        for case in CASES:
            members=[r for r in rows if r['case']==case and r['jobs']==16]
            self.assertEqual(len({(r['init'],r['variant']) for r in members}),1)
        self.assertEqual({r['phase'] for r in rows[:32]},{'native_fixed'})
        self.assertEqual({r['arm'] for r in rows[32:]},{'memrsi_evolved'})
        for gpu in (0,1):
            lane=[r for r in rows[:32] if r['gpu']==gpu]
            first_arms=[lane[index]['arm'] for index in range(0,len(lane),2)]
            self.assertEqual(first_arms.count('native'),4)
            self.assertEqual(first_arms.count('memrsi_fixed'),4)

    def test_wait_fails_on_evolution_failure_and_rejects_invalid_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);policy=root/'final-policy.json';failure=root/'failure.json'
            failure.write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'evolution_failed'):
                wait_for_policy(policy,time.monotonic()+60,threading.Event(),lambda *a,**kw:None)
            failure.unlink();policy.write_text('{"guidance":"unversioned"}')
            with self.assertRaisesRegex(ValueError,'policy_schema'):
                wait_for_policy(policy,time.monotonic()+60,threading.Event(),lambda *a,**kw:None)

    def test_first_32_run_before_global_evolution_wait_and_last_16_follow_freeze(self):
        executed=[];wait_sizes=[]
        class Runner:
            def __init__(self,out,stop):self.out=out
            def acquire(self,*args,**kwargs):pass
            def episode(self,gpu,row,orders,policy,path,progress,timeout):
                if row['arm']=='memrsi_evolved':
                    frozen=json.loads((self.out/'frozen-policies.json').read_text())
                    self.assert_frozen=frozen['evolved_policy_status']=='frozen_after_first_32_before_evolved_trials'
                    if not self.assert_frozen:raise AssertionError('unfrozen evolved trial')
                executed.append(row)
                return dict(row,status='success')
            def close(self):pass
        def wait(*args,**kwargs):
            wait_sizes.append(len(executed))
            self.assertEqual(len(executed),32)
            self.assertTrue(all(r['arm']!='memrsi_evolved' for r in executed))
            return BASE
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);orders=root/'orders.json';policy=root/'base.json'
            orders.write_text('[]');policy.write_text(json.dumps(BASE))
            args=types.SimpleNamespace(output=str(root/'output'),orders=str(orders),base_policy=str(policy),
                evolution_policy=str(root/'evolution/final-policy.json'),wait_hours=1,episode_timeout=60)
            with patch.object(physical_queue,'PhysicalRunner',Runner),patch.object(physical_queue,'wait_for_policy',wait),patch.object(physical_queue.signal,'signal'):
                physical_queue.main(args)
            report=json.loads((root/'output/report.json').read_text())
        self.assertEqual(wait_sizes,[32])
        self.assertEqual(len(executed),48)
        self.assertEqual(report['status'],'completed')
        self.assertTrue(report['identical_policies'])

    def test_physical_executors_are_byte_identical_to_validated_version(self):
        here=Path(__file__).resolve().parent
        old=here.parent/'memrsi-native-memory-v1'
        for name in PHYSICAL_FILES:
            self.assertEqual((here/name).read_bytes(),(old/name).read_bytes(),name)

    def run_case(self,case,wrong=None,fail=False):
        plan=protocol(case,'one_first',16)
        choices=plan['pre_actions']+['execute_order']*16+plan['expected_remaining']+['finish']
        if wrong:choices[len(plan['pre_actions'])+16]=wrong
        prompts=[]
        class Agent:
            def __init__(self,*args,**kwargs):
                self.policy=None;self.policy_hash="test";self.provider=types.SimpleNamespace(calls=0);self.rollovers=[]
            async def observe_only(self,text,facts):pass
            async def turn(self,text,facts,decision=False):
                prompts.append(text)
                return {'skill':choices.pop(0),'reason':'test stub'}
            async def rollover(self):self.rollovers.append({'success':True})
            async def close(self):pass
        module=types.ModuleType('agent_adapter');module.Agent=Agent;module.COMMON_TOOLS='shared test contract'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);orders=root/'orders.json'
            orders.write_text(json.dumps([{'benchmark':'libero_10','task_id':i} for i in (4,6,1,2,3,5)]))
            args=types.SimpleNamespace(output=str(root/'result'),orders=str(orders),variant=0,
                case=case,history='one_first',jobs=16,arm='native',memory_policy=None,port=0,init=0)
            with patch.dict(sys.modules,{'agent_adapter':module}),patch.object(workflow,'World',FakeWorld),patch.object(FakeWorld,'fail_kitchen',fail):
                asyncio.run(workflow.main(args))
            result=json.loads((root/'result/result.json').read_text())
        return result,prompts

    def test_all_four_conditions_reach_actual_checkpoint_after_16_jobs(self):
        for case in CASES:
            with self.subTest(case=case):
                result,prompts=self.run_case(case)
                self.assertEqual(result['status'],'success')
                self.assertEqual(len(result['rollovers']),8)
                self.assertEqual(result['arrived_checkpoint'],result['planned_checkpoint'])
                self.assertEqual(result['correct_checkpoint'],result['planned_checkpoint'])
                self.assertTrue(prompts[-1].startswith('Continue. Current scene observations:'))

    def test_incorrect_chosen_action_executes_without_scorer_substitution(self):
        result,_=self.run_case('cancel',wrong='serve_table_two')
        self.assertEqual(result['physical_executions'][17]['skill'],'serve_table_two')
        self.assertEqual(result['status'],'decision_failure')
        self.assertIn('executed_cancelled_requirement',result['memory_error_forms'])

    def test_premature_finish_is_scored_not_refused_by_program(self):
        result,_=self.run_case('resume',wrong='finish')
        self.assertEqual(result['failure'],'premature_finish')
        self.assertEqual(result['correct_checkpoint'],0)

    def test_physical_failure_has_zero_recovery_coverage_not_memory_label(self):
        result,_=self.run_case('delay',fail=True)
        self.assertEqual(result['status'],'execution_failure')
        self.assertEqual(result['arrived_checkpoint'],0)
        self.assertEqual(result['decision_errors'],[])

    def test_pair_audit_rejects_mismatched_current_scene(self):
        from portable_metrics import information_pair
        snapshot={'current_input_sha256':'same','station_state_sha256':{'one':'same','two':'same'},'action_contract_sha256':'same'}
        a={'recovery_snapshot':dict(snapshot,expected_first_private='one'),'checkpoint_choices':[{'correct':True}]}
        b={'recovery_snapshot':dict(snapshot,expected_first_private='two'),'checkpoint_choices':[{'correct':True}]}
        self.assertTrue(information_pair(a,b)['paired_correct'])
        b['recovery_snapshot']['current_input_sha256']='different'
        self.assertFalse(information_pair(a,b)['paired_correct'])


if __name__=='__main__':unittest.main()
