import collections
import copy
import unittest
from scale_protocol import cases, make_case, contract, libero_gate


class ScaleTests(unittest.TestCase):
    def test_numbers_repeats_and_all_denominators(self):
        for platform in ('twin','casa'):
            plans=cases(platform)
            self.assertEqual(len(plans),48)
            self.assertEqual(len({p['id'] for p in plans}),48)
            self.assertEqual(len({p['condition'] for p in plans}),24)
            self.assertEqual(set(collections.Counter(p['condition'] for p in plans).values()),{2})
            self.assertEqual(sum(p['planned_checkpoints'] for p in plans),132)
            for p in plans:
                self.assertEqual(sum(s['checkpoint'] for s in p['steps']),p['planned_checkpoints'])
                self.assertEqual(sum('work_order' in s for s in p['steps']),p['gap'])
                self.assertLess(2*len(p['steps'])+1,100)
                self.assertTrue(all(s['expected'] in contract(platform)[1] for s in p['steps']))

    def test_same_physical_prefix_same_resume_prompt_different_answers(self):
        for platform in ('twin','casa'):
            for kind in ('resume','delayed','revision','cancellation'):
                for gap in (4,8,16):
                    a,b=(make_case(platform,gap,kind,reverse,0) for reverse in (False,True))
                    prefix=lambda p:[(s['expected'],s.get('work_order')) for s in p['steps'] if not s['checkpoint']]
                    suffix=lambda p:[s['expected'] for s in p['steps'] if s['checkpoint']]
                    self.assertEqual(prefix(a),prefix(b))
                    self.assertNotEqual(suffix(a),suffix(b))
                    self.assertTrue(all(s['text']=='Continue.' for p in (a,b) for s in p['steps'] if s['checkpoint']))
                    self.assertNotEqual([s['text'] for s in a['steps']],[s['text'] for s in b['steps']])

    def test_cancel_is_no_replacement_and_revision_supersedes_original(self):
        for platform in ('twin','casa'):
            p=make_case(platform,8,'cancellation',False,0)
            self.assertEqual(p['planned_checkpoints'],2)
            self.assertIn('no replacement task',' '.join(s['text'] for s in p['steps']))
            p=make_case(platform,8,'revision',False,0)
            self.assertIn('replaces the earlier order',' '.join(s['text'] for s in p['steps']))
            p=make_case(platform,8,'delayed',False,0)
            self.assertIn('only after all 8',p['steps'][0]['text'])

    def test_launch_gate_does_not_equate_running_or_promotion_with_success(self):
        learning=dict(promotions=1,validation={'passed':True})
        pairs={'comparisons':{'fixed_vs_evolved':dict(paired=47,left_success=33,right_success=34),
                              'native_vs_evolved':dict(paired=46,left_success=8,right_success=34)}}
        report=dict(status='completed',physical_runs=48)
        self.assertEqual(libero_gate(None,learning,pairs)['state'],'waiting')
        self.assertEqual(libero_gate(report,learning,pairs)['state'],'ready')
        bad=copy.deepcopy(pairs);bad['comparisons']['fixed_vs_evolved']['right_success']=1
        self.assertEqual(libero_gate(report,learning,bad)['state'],'not_ready')
        self.assertEqual(libero_gate(report,{'promotions':0},pairs)['state'],'not_ready')
        self.assertEqual(libero_gate({'status':'blocked'},learning,pairs)['state'],'not_ready')


if __name__=='__main__':unittest.main()
