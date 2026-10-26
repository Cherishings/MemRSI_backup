import json
import unittest
from collections import defaultdict
from unittest.mock import patch
from io import BytesIO
from unified_pipeline import schedule_for_all, gateway_contract, matched_summary
from feedback_protocol import schedule
from pipeline_v15 import schedule as transfer

class UnifiedTests(unittest.TestCase):
    def test_three_arms_are_exact_condition_matches_and_fixed_lanes(self):
        rows=schedule_for_all(schedule((0,1,2)),transfer((0,1,2),True))
        self.assertEqual(len(rows),144)
        groups=defaultdict(list)
        for r in rows:groups[(r['dataset'],r['condition'],r['repeat'])].append(r)
        self.assertEqual(len(groups),48)
        for rs in groups.values():
            self.assertEqual({r['arm']:r['gpu'] for r in rs},{'native':0,'fixed':1,'evolved':2})
            self.assertEqual(len({(r['history'],r['init'],r['repeat']) for r in rs}),1)

    def test_gateway_rejects_old_version_before_spending_calls(self):
        for version,ok in [('recovery-v2',False),('memory-v3-tool-choice',True)]:
            with patch('unified_pipeline.urllib.request.urlopen',return_value=BytesIO(json.dumps({'model':'gpt-5.6-luna','gateway_version':version}).encode())):
                if ok:self.assertEqual(gateway_contract()['gateway_version'],version)
                else:
                    with self.assertRaises(RuntimeError):gateway_contract()

    def test_technical_failure_excluded_but_budget_failure_retained(self):
        rows=schedule_for_all(schedule((0,1,2)),transfer((0,1,2),True))[:6]
        rows=[dict(r,status='success') for r in rows]
        rows[0]['status']='infrastructure_failure'
        rows[4]['status']='budget_failure'
        with patch('unified_pipeline.summarize',return_value={}):r=matched_summary(rows,rows)
        self.assertEqual(r['comparisons']['native_vs_fixed']['paired'],1)
        self.assertEqual(r['comparisons']['fixed_vs_evolved']['paired'],2)
        self.assertEqual(r['comparisons']['fixed_vs_evolved']['improved'],1)

if __name__=='__main__':unittest.main()
