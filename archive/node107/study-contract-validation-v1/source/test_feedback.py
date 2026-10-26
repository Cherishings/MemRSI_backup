import copy,json,tempfile,unittest
from collections import Counter,defaultdict
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from feedback_protocol import histories,plan,schedule
from feedback_learning import aggregate,improves,screen_generic
from memory_policy import BASE,digest
from test_twenty import BudgetTest,response
from memory_budget import write_pair,pair
from model_provider import Provider
from token_accounting import memory_tokens

class ScheduleTest(unittest.TestCase):
    def test_complete_paired_design_with_serial_return_tasks(self):
        rows=schedule();self.assertEqual(len(rows),120)
        self.assertEqual(len({r['trial_id'] for r in rows}),120)
        self.assertEqual(Counter(r['arm'] for r in rows),dict(native=40,fixed=40,evolved=40))
        groups=defaultdict(list)
        for r in rows:groups[r['condition'],r['repeat']].append(r)
        self.assertEqual(len(groups),40)
        for g in groups.values():
            self.assertEqual({r['arm'] for r in g},{'native','fixed','evolved'})
            self.assertEqual(len({(r['gpu'],r['init'],r['history']) for r in g}),1)
        self.assertEqual({r['gpu'] for r in rows},{0,1,6,7})
        for h in histories():
            self.assertNotIn(h,('ABCDE','EDCBA'))
            p=plan(h);order=list(h);order[0],order[1]=order[1],order[0];order.append(order.pop(2))
            self.assertEqual(p['final_order_private'],order)
            self.assertIn(', '.join(h)+'.',p['initial_message'])
            self.assertEqual([x['session'] for x in p['sessions']],list(range(1,21)))
            self.assertEqual(sum(x['kind']=='partial' for x in p['sessions']),5)
            self.assertEqual([x['expected_private'] for x in p['sessions'] if x['kind']=='recovery'],['serve_'+x for x in order])
            self.assertEqual(p['updates_after_session'][10],plan(histories()[0])['updates_after_session'][10])
    def test_learning_gate_rejects_regression_invalid_unknown_cost(self):
        a=dict(correct=3,invalid=0,cost_complete=True,per_case={'bad':0,'good':3},tokens=100)
        b=dict(a,correct=4,per_case={'bad':1,'good':3},tokens=120)
        self.assertTrue(improves(a,b))
        for changes in ({'invalid':1},{'cost_complete':False},{'tokens':151},{'correct':3},{'per_case':{'bad':2,'good':2}}):
            self.assertFalse(improves(a,dict(b,**changes)))
        with self.assertRaises(ValueError):improves(a,dict(b,per_case={'different':4}))
    def test_proposal_cannot_encode_task_answers(self):
        screen_generic(BASE)
        with self.assertRaises(ValueError):screen_generic(dict(BASE,guidance='Always choose serve_D.'))
    def test_locks_reuse_standard_names(self):
        from physical_runner import LOCKS
        self.assertEqual({g:LOCKS[g] for g in (0,1,6,7)},{0:'robot-run.lock',1:'gpt-gpu1-run.lock',6:'gpt-gpu6-run.lock',7:'gpt-gpu7-run.lock'})

class CompressionFeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_measured_rejection_followed_by_valid_compaction(self):
        with tempfile.TemporaryDirectory() as d:
            a=BudgetTest().make(Path(d),'native',30)
            try:
                write_pair(a.store,('overflow '*100,''));requests=[]
                async def fake(provider,**kw):
                    requests.append(copy.deepcopy(kw))
                    return response('pack_storage',{'memory':'still too large '*100 if len(requests)==1 else 'retained fact','history':''})
                with patch.object(Provider,'_chat_attempts',fake):self.assertTrue(await a.store.fit(a.provider,'test'))
                self.assertEqual(len(requests),2)
                self.assertIn('21 tokens',requests[0]['messages'][0]['content'])
                self.assertIn(str(memory_tokens('still too large '*100,'')),requests[1]['messages'][-1]['content'])
                self.assertIn('18 combined tokens',requests[1]['messages'][-1]['content'])
                self.assertEqual(pair(a.store),('retained fact',''))
            finally:await a.close()

class FeedbackWorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, wrong=False):
        from feedback_workflow import run
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
                target = plan(histories()[0])['sessions'][self.n-1]['expected_private'] if self.n<=20 else 'finish'
                return {'skill':'serve_F' if wrong and self.n==11 else target,'reason':'test'}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);orders=root/'orders.json'
            # arrange() handles these as the two special tables plus middle jobs.
            orders.write_text(json.dumps([
                {'benchmark':'libero_10','task_id':6,'task_name':'table1'},
                {'benchmark':'libero_10','task_id':4,'task_name':'table2'},
                {'benchmark':'libero_90','task_id':0,'task_name':'kitchen'}]))
            args=SimpleNamespace(output=str(root/'run'),orders=str(orders),port=0,init=0,variant=0,
                arm='native',history=histories()[0],memory_policy=None,budget='not-read-by-fake')
            with patch('feedback_workflow.World',FakeWorld),patch('twenty_agent.TwentyAgent',FakeAgent),\
                 patch('feedback_workflow.arrange',lambda x,v:[x[-1]]):
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

