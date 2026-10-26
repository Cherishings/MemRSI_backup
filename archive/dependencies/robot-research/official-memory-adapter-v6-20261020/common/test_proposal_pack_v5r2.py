import json,hashlib,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from test_visual_rule_proposal import ProposalTests
import visual_rule_proposal as v
import source_compatibility as s
class PackTests(unittest.TestCase):
 def test_natural_from_is_not_python_import(self):
  self.assertTrue(v.heuristic_screen_procedure('Select evidence from supplied memory fragments.')['passed'])
  for text in ['from os import system','import os','from pathlib import Path']:
   with self.subTest(text=text),self.assertRaises(ValueError):v.heuristic_screen_procedure(text)

 def test_bounded_packet_keeps_all_outcomes_and_discloses_excerpts(self):
  fixture=ProposalTests();fixture.setUp()
  try:
   path=fixture.first_evidence();x=json.loads(path.read_text());x['public_initial_request']='abcdefghij'*100;x['terminal_status']='task_failure';path.write_text(json.dumps(x));before=path.read_bytes()
   def counter(messages,tools):
    d=json.loads(messages[1]['content']);return 8000 if d.get('public_text_excerpt_character_cap')==64 else 10000
   req=v.build_proposal_request(fixture.parent,fixture.path,fixture.hash,token_counter=counter)
   d=json.loads(req['messages'][1]['content']);self.assertEqual(len(d['development_cases']),12)
   e=d['development_cases'][0];self.assertEqual(e['terminal_status'],'task_failure');self.assertFalse(e['official_success'])
   note=e['public_initial_request'];self.assertEqual(note['original_chars'],len(x['public_initial_request']));self.assertEqual(note['excerpt'][0],x['public_initial_request'][:32]);self.assertEqual(note['excerpt'][1],x['public_initial_request'][-32:]);self.assertEqual(path.read_bytes(),before)
   self.assertEqual(d['parent_policy'],fixture.parent)
  finally:fixture.doCleanups()
 def test_migration_rejects_actor_change_and_unlisted_history(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(s,'ROOT',Path(tmp)):
   old={'actor.py':'unchanged','common/visual_rule_proposal.py':'old'};new={**old,'common/visual_rule_proposal.py':'new'}
   Path(tmp,'source-migration.json').write_text(json.dumps({'current_source_hashes':new,'prior_source_hashes':[old]}))
   self.assertTrue(s.execution_source_matches(old,new));self.assertFalse(s.execution_source_matches({**old,'actor.py':'other'},new))
   bad={**new,'actor.py':'changed'};Path(tmp,'source-migration.json').write_text(json.dumps({'current_source_hashes':bad,'prior_source_hashes':[old]}));self.assertFalse(s.execution_source_matches(old,bad))
if __name__=='__main__':unittest.main()
