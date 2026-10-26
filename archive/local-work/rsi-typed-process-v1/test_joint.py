import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextvars import ContextVar
from unittest.mock import patch, AsyncMock
import learn
from test_learn import policy


def proposal():
    return {'guidance_replacement': 'Check outstanding obligations against completion evidence.',
            'guidance_rationale': 'Read the retained obligation evidence.',
            'update_replacement': 'Keep outstanding obligations distinct from completion evidence.',
            'update_rationale': 'Preserve evidence the advisor reads.'}

class JointTests(unittest.TestCase):
    def test_exact_component_ablation(self):
        p=policy(); before=copy.deepcopy(p); combos=learn.joint_combinations(p,proposal())
        self.assertEqual(p,before)
        self.assertEqual(combos['g_only_edit']['update'],p['update'])
        self.assertEqual(combos['u_only_edit']['guidance'],p['guidance'])
        self.assertEqual(combos['joint']['guidance'],combos['g_only_edit']['guidance'])
        self.assertEqual(combos['joint']['update'],combos['u_only_edit']['update'])
    def test_both_edits_required_and_atomic(self):
        p=policy(); q=proposal(); del q['update_replacement']
        with self.assertRaises(ValueError): learn.joint_combinations(p,q)
        q=proposal(); q['update_replacement']='x'*1201
        with self.assertRaises(ValueError): learn.joint_combinations(p,q)
        self.assertEqual(p,policy())

class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_flow(self, invalid=False, reject=False):
        with tempfile.TemporaryDirectory() as folder:
            r=Path(folder)
            for name,value in [('parent',policy()),('train',[]),('validation',[]),('budget',{})]:
                learn.write(r/(name+'.json'),value)
            a=SimpleNamespace(root=folder,source=folder,core=folder,parent_policy=str(r/'parent.json'),
                train_manifest=str(r/'train.json'),validation_manifest=str(r/'validation.json'),budget=str(r/'budget.json'))
            module=SimpleNamespace(LEARNING_LEDGER=ContextVar('test'))
            from governance import CHECKS
            critic={k:v for key in CHECKS for k,v in [(key,'pass'),(key+'_reason','No violation'),(key+'_quote','')]}
            if reject:
                critic['preserves_advisor_interface']='fail';critic['preserves_advisor_interface_quote']='Before drawing a conclusion'
            prior=proposal();prior['guidance_replacement']='Different old generic advice.'
            learn.write(r/'previous-rejected-proposal.json', prior)
            def inspect(path,parent,role):
                self.assertEqual(role,'training');self.assertEqual(path,a.train_manifest)
                return ([{'id':'train'}],{'eligible':[]})
            async def run(args,out,stage,sources,combos,ledger):
                self.assertFalse(invalid or reject);self.assertEqual(stage,'training');self.assertEqual(set(combos),set(learn.ARMS));return []
            choice={'guidance':'separate_fact_and_summary','update':'retain_unresolved_extent'}
            if invalid:choice['extra']='untrusted text'
            structured=AsyncMock(side_effect=[(choice,None),(critic,None)])
            with patch('feedback.build',return_value={'scope':'synthetic-training','training_failure_diagnostics':[],'training_citation_contracts':[]}), patch.object(learn,'install_runtime',return_value=module),patch.object(learn,'inspect_sources',side_effect=inspect),\
                 patch.object(learn,'evidence',return_value={'training_only':True}),patch.object(learn,'single_structured',structured),\
                 patch.object(learn,'run_stage',side_effect=run):
                result=await learn.learn(a)
            self.assertEqual(structured.await_count,1 if invalid else 2)
            self.assertEqual(result["status"],"joint_proposal_rejected" if invalid or reject else "training_complete_pending_independent_selection")
            self.assertFalse(result['accepted']);self.assertEqual(result['primary_candidate'],'joint')
            self.assertFalse((r/'learning/validation').exists())
            self.assertEqual(learn.read(r/'learning/selected-policy.json'),policy())

    async def test_training_only_with_one_joint_request_and_one_critic(self):
        await self.run_flow()
    async def test_invalid_choice_stops_without_critic_or_training(self):
        await self.run_flow(invalid=True)
    async def test_critic_rejection_stops_without_training_or_retry(self):
        await self.run_flow(reject=True)

class CompilerIntegration(unittest.TestCase):
    def test_all_controller_outputs_equal_compiler(self):
        import itertools
        from process_compiler import CATALOG,compile_edit,to_patch
        p=policy()
        for g,u in itertools.product(*[list(v) for v in CATALOG.values()]):
            c={'guidance':g,'update':u}
            self.assertEqual(learn.procedures(learn.joint_combinations(p,to_patch(p,c))['joint']),learn.procedures(compile_edit(p,c)))
