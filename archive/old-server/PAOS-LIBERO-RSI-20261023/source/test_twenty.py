import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PhyAgentOS.providers.base import LLMResponse, ToolCallRequest
from model_provider import Provider
from memory_budget import BoundedStore, pair, write_pair
from token_accounting import memory_tokens
from twenty_agent import TwentyAgent
from twenty_protocol import plan, restore_input
from types import SimpleNamespace

def response(name, data):
    return LLMResponse(content=None, finish_reason='tool_calls',
        tool_calls=[ToolCallRequest('call-test', name, data)])

class ProtocolTest(unittest.TestCase):
    def test_serial_schedule_and_history_dependency(self):
        a, b = plan('alpha'), plan('beta')
        self.assertEqual([s['session'] for s in a['sessions']], list(range(1, 21)))
        self.assertEqual(a['session_switches'], 19)
        self.assertEqual(sum(s['kind'] == 'partial' for s in a['sessions']), 5)
        self.assertEqual(sum(s['kind'] == 'kitchen' for s in a['sessions']), 9)
        self.assertEqual(a['sessions'][:10], b['sessions'][:10])
        self.assertNotEqual(a['sessions'][10]['expected_private'], b['sessions'][10]['expected_private'])
        visible = restore_input({'serve_A': {'object_positions': [1, 2]}})
        self.assertNotIn('expected', visible)
        self.assertNotIn(a['final_order_private'][0] + ',', visible)
        self.assertEqual(visible, restore_input({'serve_A': {'object_positions': [1, 2]}}))

class BudgetTest(unittest.IsolatedAsyncioTestCase):
    def make(self, root, arm, limit=512):
        out = root / 'runs' / arm
        policy = root / 'policy.json'
        from memory_design import SEED,policy as compile_policy
        design=copy.deepcopy(SEED);design.update(read_focus='TEST_G',retention_focus='TEST_U')
        policy.write_text(json.dumps(compile_policy(design)))
        with patch('model_provider.read_api_key', return_value='offline-key'):
            return TwentyAgent(arm, out, policy if arm == 'memrsi' else None,
                {'persistent_tokens': limit, 'active_input_tokens': 8192})

    async def test_equal_limits_native_no_gu_and_no_finish_veto(self):
        with tempfile.TemporaryDirectory() as d:
            agents = [self.make(Path(d), arm) for arm in ('native', 'memrsi')]
            try:
                x, y = agents
                self.assertEqual(x.loop.tools.get_definitions(), y.loop.tools.get_definitions())
                self.assertEqual((x.workspace/'TOOLS.md').read_text(), (y.workspace/'TOOLS.md').read_text())
                self.assertIsNone(x.ops)
                self.assertEqual(x.policy, {'schema': 1, 'guidance': '', 'update': ''})
                self.assertEqual(x.store.limit, y.store.limit)
                await x.action.execute('finish', 'Nothing left')
                self.assertEqual(x.action.records[0]['skill'], 'finish')
            finally:
                for a in agents: await a.close()

    async def test_overflow_rolls_back_both_files_and_preserves_short(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.make(Path(d), 'native', 30)
            try:
                write_pair(a.store, ('old memory', 'old history'))
                await a.observe_only('Unarchived execution feedback')
                before = copy.deepcopy(a.loop.sessions.get_or_create(a.session_key).messages)
                async def fake(provider, **kw):
                    name = kw['tools'][0]['function']['name']
                    if name == 'save_memory':
                        return response(name, {'memory_update': 'very long memory ' * 50, 'history_entry': 'new entry'})
                    return response(name, {'memory': 'still too large ' * 50, 'history': ''})
                with patch.object(Provider, '_chat_attempts', fake):
                    with self.assertRaisesRegex(RuntimeError, 'persistent_memory_budget_exhausted'):
                        await a.rollover()
                self.assertEqual(pair(a.store), ('old memory', 'old history'))
                self.assertEqual(before, a.loop.sessions.get_or_create(a.session_key).messages)
            finally: await a.close()

    async def test_history_cannot_bypass_capacity_or_access_old_session(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.make(Path(d), 'native', 30)
            try:
                write_pair(a.store, ('keep this', 'history'))
                before = pair(a.store)
                tool = a.loop.tools.get('write_file')
                result = await tool.execute(path='memory/HISTORY.md', content='overflow word ' * 100)
                self.assertIn('not committed', result)
                self.assertEqual(before, pair(a.store))
                result = await tool.execute(path='SECRET.md', content='alternate persistent ledger')
                self.assertIn('denied', result)
                self.assertFalse((a.workspace/'SECRET.md').exists())
                result = await a.loop.tools.get('read_file').execute(path='sessions/old.jsonl')
                self.assertIn('denied', result)
                result = await a.loop.tools.get('read_file').execute(path='../another-trial/result.json')
                self.assertIn('denied', result)
            finally: await a.close()

    async def test_successful_pack_and_latest_update_then_clear(self):
        for arm in ('native', 'memrsi'):
            with tempfile.TemporaryDirectory() as d:
                a = self.make(Path(d), arm, 30)
                try:
                    await a.observe_only('PUBLIC_LATEST')
                    requests = []
                    async def fake(provider, **kw):
                        requests.append(kw)
                        name = kw['tools'][0]['function']['name']
                        if name == 'save_memory':
                            self.assertEqual('TEST_U' in json.dumps(kw), arm == 'memrsi')
                            self.assertIn('PUBLIC_LATEST', json.dumps(kw))
                            return response(name, {'memory_update': 'long ' * 100, 'history_entry': 'receipt'})
                        self.assertEqual('TEST_U' in json.dumps(kw), arm == 'memrsi')
                        return response(name, {'memory': 'selected facts', 'history': 'receipt'})
                    with patch.object(Provider, '_chat_attempts', fake): await a.rollover()
                    self.assertEqual(len(requests), 2)
                    self.assertEqual(pair(a.store), ('selected facts', 'receipt'))
                    self.assertEqual(a.loop.sessions.get_or_create(a.session_key).messages, [])
                finally: await a.close()

    async def test_short_guidance_has_no_consolidated_history(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.make(Path(d), 'memrsi')
            try:
                await a.observe_only('ARCHIVED_SENTINEL')
                await a.observe_only('CURRENT_EVENT')
                s = a.loop.sessions.get_or_create(a.session_key);s.last_consolidated=1
                async def guide(messages, current):
                    self.assertNotIn('ARCHIVED_SENTINEL', json.dumps(messages))
                    self.assertIn('CURRENT_EVENT', json.dumps(messages))
                    return 'test guide'
                async def process(*args, **kwargs):
                    await a.action.execute('finish', 'test');return 'done'
                with patch.object(a.ops, 'guide', guide), patch.object(a.loop, 'process_direct', process):
                    await a.turn('Continue', decision=True)
            finally: await a.close()

    async def test_active_limit_stops_before_transport(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.make(Path(d), 'native')
            try:
                a.provider.budget['active_input_tokens'] = 20
                with self.assertRaisesRegex(RuntimeError, 'active_context_budget_exceeded'):
                    await a.provider._chat_attempts_locked(messages=[{'role':'user','content':'x y z ' * 100}])
                self.assertEqual(a.provider.calls, 0)
            finally: await a.close()

class WorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, wrong=False):
        from twenty_workflow import run
        executions = []
        instances = []
        class FakeWorld:
            def __init__(self, out, port, init, order):
                self.out = Path(out); self.out.mkdir(parents=True)
                (self.out/'physical').mkdir()
                (self.out/'physical/initial.json').write_text(json.dumps({'instruction':'current test kitchen job'}))
                self.count = 0;self.steps = 0;self.initial = self.send(op='observe')
            def send(self, op, **kw):
                if op == 'observe':
                    return {'scene_observation':{'objects':{'placed_count':self.count}},
                            'state_sha256':str(self.count), 'steps':self.steps}
                if op == 'execute':
                    executions.append(self.out.name)
                    before = {'first':self.count>0, 'second':self.count>1}
                    self.count = 1 if kw.get('stop_after_one') else 2;self.steps += 10
                    return {'success':True,'native_task_complete':self.count==2,
                        'stop_after_one':kw.get('stop_after_one',False), 'components_before':before,
                        'components_after':{'first':self.count>0,'second':self.count>1},
                        'already_satisfied':False,'attempts':[],'after':self.send(op='observe')}
            def close(self): pass
        class FakeAgent:
            def __init__(self,*args):
                self.n=0;self.rollovers=[];self.requests=[];instances.append(self)
            async def observe_only(self,text):pass
            async def rollover(self):self.rollovers.append({'success':True})
            async def close(self):pass
            async def turn(self,text,decision):
                self.requests.append(text);self.n+=1
                target = plan('alpha')['sessions'][self.n-1]['expected_private'] if self.n<=20 else 'finish'
                return {'skill':'serve_F' if wrong and self.n==11 else target,'reason':'test'}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);orders=root/'orders.json'
            # arrange() handles these as the two special tables plus middle jobs.
            orders.write_text(json.dumps([
                {'benchmark':'libero_10','task_id':6,'task_name':'table1'},
                {'benchmark':'libero_10','task_id':4,'task_name':'table2'},
                {'benchmark':'libero_90','task_id':0,'task_name':'kitchen'}]))
            args=SimpleNamespace(output=str(root/'run'),orders=str(orders),port=0,init=0,variant=0,
                arm='native',history='alpha',memory_policy=None,budget='not-read-by-fake')
            with patch('twenty_workflow.World',FakeWorld),patch('twenty_agent.TwentyAgent',FakeAgent),\
                 patch('twenty_workflow.arrange',lambda x,v:[x[-1]]):
                result=await run(args)
            return result,executions,instances[0]

    async def test_complete_serial_workflow_and_nineteen_archives(self):
        r,executions,agent=await self.exercise()
        self.assertEqual(r['status'],'success')
        self.assertEqual(len(executions),20)
        self.assertEqual(len(agent.rollovers),19)
        self.assertEqual(r['correct_checkpoints'],7)
        self.assertEqual(r['partial_successes'],5)
        self.assertEqual(r['recovery_successes'],5)
        self.assertTrue(all(x['unselected_tables_unchanged'] for x in r['snapshot_checks']))
        self.assertTrue(agent.requests[10].startswith('Continue. Current scene observations:'))
        self.assertNotIn('expected_private',agent.requests[10])

    async def test_wrong_chosen_action_not_replaced_with_answer(self):
        r,executions,agent=await self.exercise(wrong=True)
        self.assertEqual(r['status'],'decision_failure')
        self.assertEqual(r['failure'],'wrong_task_or_order')
        self.assertEqual(executions[-1],'table-F')
        self.assertEqual(r['reached_checkpoints'],1)
        self.assertEqual(r['correct_checkpoints'],0)
        self.assertEqual(r['planned_checkpoints'],7)

if __name__ == '__main__': unittest.main()
