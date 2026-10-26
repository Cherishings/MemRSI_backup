import unittest, tempfile, json
from pathlib import Path
from citation_contract import classify, collect
class CitationContractTests(unittest.TestCase):
    def test_event_ids_are_not_source_keys(self):
        self.assertEqual(classify({'recommendation':'next','basis_ids':['Event 44']},['memory','history','current']),'outside_source_enum')
        self.assertEqual(classify({'recommendation':'next','basis_ids':['memory']},['memory','history','current']),'valid_citation')
    def test_distinct_validation_reasons(self):
        for ids,expected in [(None,'not_array'),(['memory']*6,'too_many'),(['memory']*2,'duplicate'),([],'missing_nonempty_recommendation_basis')]:
            self.assertEqual(classify({'recommendation':'next','basis_ids':ids},['memory']),expected)
        self.assertEqual(classify({'recommendation':'','basis_ids':[]},['memory']),'valid_citation')
    def test_no_nontraining_or_symlink_trace(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);train=root/'training';train.mkdir();other=root/'validation';other.mkdir()
            with self.assertRaises(AssertionError):collect(other,train)
            (other/'trace').write_text('')
            (train/'model-trace.jsonl').symlink_to(other/'trace')
            with self.assertRaises(AssertionError):collect(train,train)
    def test_extract_all_counts_without_task_answers(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); schema={'properties':{'basis_ids':{'items':{'enum':['current']}}}}
            rows=[]
            for i,ids in enumerate([['current'],['E1'],['E2']]):
                rows.append({'call':i,'request':{'tools':[{'function':{'name':'report_advice','parameters':schema}}]},'response':{'tool_calls':[{'name':'report_advice','arguments':{'recommendation':'PRIVATE_ACTION','basis_ids':ids}}]}})
            (p/'model-trace.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            out=collect(p,p)
            self.assertEqual(out['counts'],{'valid_citation':1,'outside_source_enum':2})
            self.assertEqual(len(out['examples']),2)
            self.assertNotIn('PRIVATE_ACTION',json.dumps(out))
