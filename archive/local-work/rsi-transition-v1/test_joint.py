import copy
import sys
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
    async def test_training_only_with_one_joint_request_and_one_critic(self):
        await self.flow(False)

    async def test_critic_rejection_has_zero_training(self):
        await self.flow(True)

    async def flow(self, reject):
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
                critic['generic']='fail';critic['generic_reason']='Synthetic failure';critic['generic_quote']='Check outstanding obligations'
            prior=proposal();prior['guidance_replacement']='Different old generic advice.'
            learn.write(r/'previous-rejected-proposal.json', prior)
            def inspect(path,parent,role):
                self.assertEqual(role,'training');self.assertEqual(path,a.train_manifest)
                return ([{'id':'train'}],{'eligible':[]})
            async def run(args,out,stage,sources,combos,ledger):
                self.assertFalse(reject)
                self.assertEqual(stage,'training');self.assertEqual(set(combos),set(learn.ARMS));return []
            structured=AsyncMock(side_effect=[(proposal(),None),(critic,None)])
            with patch.dict(sys.modules,{'token_accounting':SimpleNamespace(request_tokens=lambda m,t:1)}), patch('prepared.load',return_value=({'messages':[],'tools':[]},['old'],{})), patch.object(learn,'install_runtime',return_value=module),patch.object(learn,'inspect_sources',side_effect=inspect),\
                 patch.object(learn,'evidence',return_value={'training_only':True}),patch.object(learn,'single_structured',structured),\
                 patch.object(learn,'run_stage',side_effect=run):
                result=await learn.learn(a)
            self.assertEqual(structured.await_count,2)
            self.assertEqual(result['status'],'joint_proposal_rejected' if reject else 'training_complete_pending_independent_selection')
            self.assertFalse(result['accepted']);self.assertEqual(result['primary_candidate'],'joint')
            self.assertFalse((r/'learning/validation').exists())
            self.assertEqual(learn.read(r/'learning/selected-policy.json'),policy())
