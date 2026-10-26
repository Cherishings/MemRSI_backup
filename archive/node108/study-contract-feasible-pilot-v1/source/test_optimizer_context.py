import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from optimizer_context import prepare,LIMIT
from stream_design import SCHEMA,SEED_PROCEDURES,compile_procedures
from structured_feedback import CRITIC
from repair_learning import RepairExperiment,initialize_repair
from replay import dump

class PackingTest(unittest.TestCase):
    def data(self):
        return {'parent':copy.deepcopy(SEED_PROCEDURES),'current_batch_feedback':[
          {'id':f'case-{i}','status':'decision_failure','completed_sessions':17,'physical_successes':16,
           'decisions':[{'session':17,'skill':'finish','expected_private':'continue','correct':False,'reason':'解释 '*4000}],
           'recent_public_events':[{'id':'event','decision_requested':True,'text':'历史任务反馈 '*2000}],
           'long_memory_excerpt':'已完成和未完成任务 '*3000,'guidance_excerpt':'依据旧记录 '*2000} for i in range(5)],'prior_rounds':[]}
    def test_large_evidence_and_retry_preserve_facts(self):
        data=self.data();original=copy.deepcopy(data)
        for extra in ([],[{'role':'user','content':'format error '+('x '*2500)}]):
            msgs,tools,audit=prepare('Improve rules',data,SCHEMA,extra)
            packed=json.loads(msgs[1]['content'])
            self.assertLessEqual(audit['after_tokens'],LIMIT)
            self.assertEqual(packed['parent'],data['parent'])
            self.assertEqual(len(packed['current_batch_feedback']),5)
            for a,b in zip(data['current_batch_feedback'],packed['current_batch_feedback']):
                for k in ('id','status','completed_sessions','physical_successes'):self.assertEqual(a[k],b[k])
                for k in ('skill','correct','expected_private'):self.assertEqual(a['decisions'][0][k],b['decisions'][0][k])
        self.assertEqual(data,original)
    def test_small_input_and_critic_rules_unchanged(self):
        data={'guidance':'g'*1600,'update':'u'*1600,'rationale':'r '*30000}
        msgs,_,_=prepare('Check',data,CRITIC)
        packed=json.loads(msgs[1]['content'])
        for k in ('guidance','update'):self.assertEqual(packed[k],data[k])
        small={'parent':SEED_PROCEDURES}
        msgs,_,audit=prepare('Check',small,SCHEMA)
        self.assertEqual(json.loads(msgs[1]['content']),small)
        self.assertFalse(audit['packing_applied'])
    def test_unshrinkable_rules_block_without_call(self):
        with self.assertRaisesRegex(ValueError,'cannot_fit'):
            prepare('Check',{'parent':'immutable '*20000},SCHEMA)

class ReuseTest(unittest.TestCase):
    def test_same_policy_preserves_capability_and_exhausted_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';new=root/'new';policy=compile_procedures(SEED_PROCEDURES)
            dump(old/'round-1/parent-policy.json',policy);dump(new/'round-1/parent-policy.json',policy)
            attempts=[{'trial_id':'a','attempt':1,'status':'decision_failure'},
                      {'trial_id':'b','attempt':3,'status':'infrastructure_failure'}]
            dump(old/'round-1/physical/attempts.json',attempts)
            e=object.__new__(RepairExperiment);e.old_learning=old
            with patch('repair_learning.ParallelExperiment.batch',return_value=[]) as call:
                e.batch([],{'memrsi':new/'round-1/parent-policy.json'},new/'round-1/physical')
                got=call.call_args.kwargs['inherited'];self.assertEqual(len(got),2)
                self.assertEqual([x['attempt'] for x in got],[1,3])
                changed=dict(policy,guidance=policy['guidance']+' Changed.')
                dump(new/'round-1/parent-policy.json',changed)
                e.batch([],{'memrsi':new/'round-1/parent-policy.json'},new/'round-1/physical')
                self.assertEqual(call.call_args.kwargs['inherited'],())
    def test_old_rejected_proposal_and_call_budget_not_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'old';new=Path(tmp)/'new'
            dump(old/'learning-call-ledger.json',{'calls':123,'limit':6000})
            dump(old/'round-0/decision.json',{'accepted':False,'reason':'invalid_probe'})
            dump(old/'round-0/parent-policy.json',compile_procedures(SEED_PROCEDURES))
            initialize_repair(old,new);initialize_repair(old,new)
            self.assertEqual(json.loads((new/'learning-call-ledger.json').read_text())['calls'],123)
            self.assertEqual((new/'round-0/decision.json').read_bytes(),(old/'round-0/decision.json').read_bytes())
if __name__=='__main__':unittest.main()
