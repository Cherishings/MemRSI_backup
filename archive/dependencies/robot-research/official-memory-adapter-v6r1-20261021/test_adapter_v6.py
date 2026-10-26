import ast,asyncio,json,sys,types,unittest,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'common'))
from observation_evidence import OBSERVATION_SCHEMA,validate_observation,render_observation
# Extract the actual common tool class, without importing model/GPU dependencies.
tree=ast.parse((ROOT/'common/visual_actor.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='InstructionAction')
scope={'Tool':object,'OBSERVATION_SCHEMA':OBSERVATION_SCHEMA,'validate_observation':validate_observation,'render_observation':render_observation}
exec(compile(ast.Module(body=[node],type_ignores=[]),'real_common_action','exec'),scope)
mod=types.ModuleType('visual_actor');mod.InstructionAction=scope['InstructionAction'];mod.VisualAgent=type('VisualAgent',(),{});mod.CONTRACT='';sys.modules['visual_actor']=mod
from adapted_action_contract import AtomicCoverAction,FixedTaskAction,atomic_instruction,validate_completion
from archive_transport_evidence import transport_evidence
OBS={'visible_facts':'cover appears over block','progress_uncertainty':'order not established','reference_to_preserve':'previous visible colors'}
E={'observed_history':'No confirmed prior sequence','unverified_obligations':'ordered completion unknown'}
class Tests(unittest.TestCase):
 def act(self,a,**kw):a.event_id=1;return asyncio.run(a.execute(reason='test',observation=OBS,completion_evidence=E,**kw))
 def test_single_atomic_format(self):
  for target in ['left','middle','right']:
   self.assertEqual(atomic_instruction('cover',target),f'Cover the {target} block with the {target} cover.')
   self.assertEqual(atomic_instruction('open',target),f'Open the {target} cover to uncover the blocks in the order of red, green, and blue.')
 def test_cannot_smuggle_multi_step(self):
  for target in ['left and right','red','hidden_state']:
   with self.assertRaises(ValueError):atomic_instruction('cover',target)
 def test_continue_keeps_committed_instruction(self):
  a=AtomicCoverAction();self.act(a,skill='execute',primitive='cover',target='left',continuity='start');first=a.records[-1]['instruction'];a.records=[]
  self.act(a,skill='execute',primitive='none',target='none',continuity='continue');self.assertEqual(a.records[-1]['instruction'],first)
 def test_replace_is_explicit(self):
  a=AtomicCoverAction();self.act(a,skill='execute',primitive='cover',target='left',continuity='start');a.records=[]
  self.act(a,skill='execute',primitive='open',target='right',continuity='replace');self.assertIn('right',a.records[-1]['instruction']);self.assertEqual(a.records[-1]['continuity'],'replace')
 def test_no_automatic_order(self):
  a=AtomicCoverAction();self.act(a,skill='execute',primitive='open',target='right',continuity='start');self.assertEqual(a.records[-1]['primitive'],'open')
 def test_finish_not_vetoed(self):
  a=AtomicCoverAction();self.act(a,skill='finish',primitive='none',target='none',continuity='none');self.assertEqual(a.records[-1]['skill'],'finish')
 def test_invalid_continue_cannot_dispatch(self):
  a=AtomicCoverAction();self.act(a,skill='execute',primitive='none',target='none',continuity='continue');self.assertEqual(a.records,[])
 def test_no_double_dispatch(self):
  a=AtomicCoverAction();self.act(a,skill='execute',primitive='cover',target='left',continuity='start');self.act(a,skill='finish',primitive='none',target='none',continuity='none');self.assertEqual(len(a.records),1)
 def test_no_instruction_argument(self):
  for cls in [AtomicCoverAction,FixedTaskAction]:self.assertNotIn('instruction',cls.parameters['properties'])
 def test_remem_fixed_goal(self):
  a=FixedTaskAction('Wash then return the banana.');self.act(a,skill='execute');first=a.records[-1]['instruction'];a.records=[];self.act(a,skill='execute');self.assertEqual(a.records[-1]['instruction'],first)
 def test_remem_finish_not_vetoed(self):
  a=FixedTaskAction('Wash the object.');self.act(a,skill='finish');self.assertEqual(a.records[-1]['instruction'],'')
 def test_evidence_bound(self):
  with self.assertRaises(ValueError):validate_completion(dict(E,hidden_success=True))
  with self.assertRaises(ValueError):validate_completion(dict(E,observed_history='x'*513))
 def test_fresh_disjoint_splits(self):
  from adaptation_protocol import SPLITS
  self.assertEqual([len(SPLITS[s]) for s in ['development','validation','test']],[12,12,48]);self.assertEqual(len(set(sum((list(s) for s in SPLITS.values()),[]))),72);self.assertGreaterEqual(min(SPLITS['development']),3000)
 def test_transport_requires_same_failed_archive_call(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'rollover-10').mkdir();(p/'rollover-9').mkdir()
   (p/'rollover-9/audit.json').write_text(json.dumps(dict(success=True,model_calls=9)))
   (p/'rollover-10/audit.json').write_text(json.dumps(dict(success=False,model_calls=10)))
   (p/'model-errors.jsonl').write_text(json.dumps(dict(call=9,http_status=429)))
   self.assertIsNone(transport_evidence(p,dict(error_code='native_session_archival_failed')))
   (p/'model-errors.jsonl').write_text(json.dumps(dict(call=10,http_status=429)))
   self.assertIsNotNone(transport_evidence(p,dict(error_code='native_session_archival_failed')))
if __name__=='__main__':unittest.main()
