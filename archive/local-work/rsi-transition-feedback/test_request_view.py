import json,unittest
from pathlib import Path
from paired import build_view
from request_view import line_pack,assemble
class RequestTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.view=build_view(json.loads((Path(__file__).parent/'training-transitions.json').read_text()))
 def test_line_roundtrip(self):
  v=self.view;p=line_pack(v)
  for a,b in zip(v['paired']+[v['diagnostic']],p['paired']+[p['diagnostic']]):
   for x,y in zip(a['details'],b['details']):
    for name,h in x['refs'].items():self.assertEqual(v['shared_text'][h],''.join(p['memory_lines'][i] for i in p['memories'][y['refs'][name]]))
 def test_assembly_preserves_contract(self):
  parent={'guidance':'original','update':'unchanged'};schema={'type':'object'};runtime={'functions':'fixed'};errors={'failed':True}
  x=assemble(self.view,parent,schema,runtime,errors,'system');d=json.loads(x['messages'][1]['content'])
  self.assertEqual(d['parent'],parent);self.assertEqual(d['existing_runtime_contract'],runtime);self.assertEqual(d['training_failure_diagnostics'],errors);self.assertEqual(x['tools'][0]['function']['parameters'],schema)
 def test_no_mutation(self):
  before=json.dumps(self.view,sort_keys=True);line_pack(self.view);self.assertEqual(before,json.dumps(self.view,sort_keys=True))
 def test_full_request_coverage(self):
  x=json.loads((Path(__file__).parent/'full-request.json').read_text());d=json.loads(x['messages'][1]['content']);v=d['training_archive_transitions']
  self.assertEqual(len(v['summaries']),32);self.assertEqual(len(v['paired']),8);self.assertEqual(len(v['diagnostic']['details']),1);self.assertEqual(len(d['training_failure_diagnostics']['output_limits']),8)
if __name__=='__main__':unittest.main()
