import copy,unittest
from resume_v15 import project
from memory_design import SEED
class Recovery(unittest.TestCase):
    def response(self,d):return {'finish_reason':'tool_calls','tool_calls':[{'name':'submit','arguments':d}]}
    def test_preserves_operative_fields(self):
        d=copy.deepcopy(SEED);d['priority']='explanation only'
        got,ignored=project(self.response(d))
        self.assertEqual(got,SEED);self.assertEqual(ignored,['priority'])
    def test_rejects_missing_or_unknown(self):
        d=copy.deepcopy(SEED);del d['fields']
        with self.assertRaises(ValueError):project(self.response(d))
        d=copy.deepcopy(SEED);d['new_instruction']='do something'
        with self.assertRaises(ValueError):project(self.response(d))
    def test_rejects_invalid_required_values(self):
        d=copy.deepcopy(SEED);d['fields']=['status']
        with self.assertRaises(ValueError):project(self.response(d))
if __name__=='__main__':unittest.main()
