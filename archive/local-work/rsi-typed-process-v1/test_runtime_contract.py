import unittest,tempfile
from pathlib import Path
from runtime_contract import extract
class RuntimeTests(unittest.TestCase):
    def test_only_frozen_functions_no_execution(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'method.py'
            p.write_text('raise RuntimeError("DO_NOT_EXECUTE")\ndef unrelated(): return "HIDDEN"\ndef public_payload(): return 1\ndef advice_tools(): return 2\ndef validate_advice(): return 3\n')
            v=extract(p)
            self.assertEqual(set(v['functions']),{'public_payload','advice_tools','validate_advice'})
            self.assertNotIn('HIDDEN',str(v));self.assertNotIn('DO_NOT_EXECUTE',str(v))
    def test_missing_function_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'method.py';p.write_text('def advice_tools(): pass\n')
            with self.assertRaises(ValueError):extract(p)
