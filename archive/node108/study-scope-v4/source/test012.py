import unittest,tempfile,json
from pathlib import Path
from queue012 import disconnected,GPUS
from pipeline_v15 import schedule
class Tests(unittest.TestCase):
    def test_restricted_assignment(self):
        rows=schedule(GPUS,True)
        self.assertEqual(len(rows),24);self.assertEqual({r['gpu'] for r in rows},{0,1,2})
        for c in {r['condition'] for r in rows}:
            self.assertEqual(len({r['gpu'] for r in rows if r['condition']==c}),1)
    def test_no_capability_retry(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t,'model-errors.jsonl').write_text(json.dumps({'exception_type':'APIConnectionError','http_status':None})+'\n')
            self.assertTrue(disconnected({'status':'infrastructure_failure','output':t}))
            for status in ('success','decision_failure','execution_failure','budget_failure'):
                self.assertFalse(disconnected({'status':status,'output':t}))
if __name__=='__main__':unittest.main()
