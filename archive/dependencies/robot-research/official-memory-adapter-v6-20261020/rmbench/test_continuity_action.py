import ast,asyncio,copy,importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch

class ContinuityTests(unittest.TestCase):
    def action(self):
        # Execute the actual inherited action implementation without a model/provider.
        source=Path(__file__).parents[1]/'common/visual_actor.py'
        tree=ast.parse(source.read_text())
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='InstructionAction')
        scope={'Tool':object,'OBSERVATION_SCHEMA':{},'validate_observation':lambda x:x,
               'render_observation':lambda i,x:'observed'}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
        fake=types.SimpleNamespace(VisualAgent=object,InstructionAction=scope['InstructionAction'],CONTRACT='')
        spec=importlib.util.spec_from_file_location('tested_rmb',Path(__file__).with_name('rmb_visual_actor.py'))
        m=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'visual_actor':fake}):spec.loader.exec_module(m)
        return m.ContinuityAction()

    def submit(self,a,skill,instruction,mode,reason='current observation'):
        return asyncio.run(a.execute(skill,instruction,reason,{},mode))

    def test_continue_preserves_exact_command_across_changed_reason(self):
        a=self.action();self.submit(a,'execute','cover red','start');a.records.clear()
        self.submit(a,'execute','','continue','Still covering; changed wording')
        self.assertEqual(a.records[0]['instruction'],'cover red')
        self.assertEqual(a.records[0]['continuity'],'continue')
        self.assertEqual(a.records[0]['submitted_instruction'],'')

    def test_no_silent_retarget_on_continue(self):
        a=self.action();self.submit(a,'execute','cover red','start');a.records.clear()
        self.submit(a,'execute','cover blue','continue');self.assertEqual(a.records,[])
        self.assertEqual(a.committed_instruction,'cover red')

    def test_explicit_replace_can_change_target(self):
        a=self.action();self.submit(a,'execute','cover red','start');a.records.clear()
        self.submit(a,'execute','cover blue','replace');self.assertEqual(a.committed_instruction,'cover blue')

    def test_finish_not_vetoed(self):
        a=self.action();self.submit(a,'execute','cover red','start');a.records.clear()
        self.submit(a,'finish','','none');self.assertEqual(a.records[0]['skill'],'finish')

    def test_continue_without_command_is_rejected(self):
        a=self.action();self.submit(a,'execute','','continue');self.assertEqual(a.records,[])

    def test_duplicate_commit_cannot_change_command(self):
        a=self.action();self.submit(a,'execute','cover red','start')
        self.submit(a,'execute','cover blue','replace');self.assertEqual(a.committed_instruction,'cover red')
        self.assertEqual(len(a.records),1)

if __name__=='__main__':unittest.main()
