import ast,asyncio,json,tempfile,unittest
from types import SimpleNamespace
from pathlib import Path
from observation_evidence import OBSERVATION_SCHEMA,validate_observation,render_observation

def action_class():
 tree=ast.parse((Path(__file__).parent/'visual_actor.py').read_text())
 node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='InstructionAction')
 scope={'Tool':object,'OBSERVATION_SCHEMA':OBSERVATION_SCHEMA,'validate_observation':validate_observation,'render_observation':render_observation}
 exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'extracted_action','exec'),scope)
 return scope['InstructionAction']
class Integration(unittest.TestCase):
 def setUp(self):self.a=action_class()();self.a.event_id=7;self.note={'visible_facts':'Object in gripper','progress_uncertainty':'Washing not established','reference_to_preserve':'left of sink'}
 def test_evidence_in_public_tool_receipt(self):
  text=asyncio.run(self.a.execute('execute','wash','requested',self.note));self.assertIn('Event 7',text);self.assertIn('Washing not established',text);self.assertIn('not an execution receipt',text);self.assertEqual(len(self.a.records),1)
 def test_finish_not_vetoed_by_uncertainty(self):
  asyncio.run(self.a.execute('finish','','model chooses finish',self.note));self.assertEqual(self.a.records[0]['skill'],'finish')
 def test_bad_observation_cannot_commit_action(self):
  with self.assertRaises(ValueError):asyncio.run(self.a.execute('execute','wash','x',dict(self.note,hidden_success=True)))
  self.assertEqual(self.a.records,[])
 def test_duplicate_commit_rejected(self):
  asyncio.run(self.a.execute('execute','wash','x',self.note));reply=asyncio.run(self.a.execute('finish','','x',self.note));self.assertIn('Rejected',reply);self.assertEqual(len(self.a.records),1)
 def test_all_arms_share_schema(self):
  self.assertIn('observation',self.a.parameters['required']);self.assertEqual(self.a.parameters['properties']['observation'],OBSERVATION_SCHEMA)
 def test_same_native_archive(self):
  text=(Path(__file__).parent/'visual_actor.py').read_text();self.assertIn('native_archive_algorithm_changed=False',text);self.assertNotIn('official_check_success',text)
 def test_public_input_is_audited_before_failed_decision_for_both_arms(self):
  import numpy as np
  tree=ast.parse((Path(__file__).parent/'visual_actor.py').read_text())
  cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='VisualAgent')
  node=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='choose')
  scope={'json':json,'MAX_CAMERAS':2,'MAX_IMAGE_EDGE':128,'public_proprio':lambda p: p,
         'image_evidence':lambda p: []}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'extracted_choose','exec'),scope)
  for arm in ('native','memrsi'):
   with self.subTest(arm=arm),tempfile.TemporaryDirectory() as td:
    output=Path(td);workspace=output/'workspace';(workspace/'memory').mkdir(parents=True)
    (workspace/'memory/MEMORY.md').write_text('A public pending request.')
    audit=[]
    async def fail_turn(*args,**kwargs):raise ValueError('invalid first action')
    obj=SimpleNamespace(output=output,workspace=workspace,event_id=0,
        action=SimpleNamespace(event_id=0),provider=SimpleNamespace(_append=lambda f,v:audit.append((f,v))),turn=fail_turn)
    with self.assertRaisesRegex(ValueError,'invalid first action'):
     asyncio.run(scope['choose'](obj,'Actual public request',[np.zeros((2,2,3),dtype=np.uint8)],{}))
    saved=[v for f,v in audit if f=='public-decision-inputs.jsonl']
    self.assertEqual(len(saved),1)
    self.assertEqual(set(saved[0]),{'event_id','public_request','memory_before','snapshot_scope'})
    self.assertEqual(saved[0]['public_request'],'Actual public request')
    self.assertIn('A public pending request.',saved[0]['memory_before'])
    self.assertFalse(any(f=='public-action-audit.jsonl' for f,v in audit))
    self.assertIsNone(obj._visual_pending)
if __name__=='__main__':unittest.main()
