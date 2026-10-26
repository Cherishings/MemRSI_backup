import copy,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from model_provider import retry_transport
import experiment_recovery as module

class Transport(unittest.TestCase):
    def test_buffered_disconnect_retries_but_not_output_or_auth_errors(self):
        e=dict(http_status=502,stage='stream',upstream_http_status=200,
               upstream_error_type='ConnectionError',output_started=True,retryable=False)
        self.assertTrue(retry_transport(e,0,0))
        for change in ({'code':'generation_output_limit'},{'http_status':401},
                       {'upstream_error_type':'ValueError'},{'stage':'unknown'}):
            self.assertFalse(retry_transport(dict(e,**change),0,0))
        self.assertFalse(retry_transport(e,4,0));self.assertFalse(retry_transport(e,0,20))
    def test_ability_errors_never_retry(self):
        for status in ('success','decision_failure','execution_failure','protocol_failure','budget_failure'):
            self.assertFalse(module.retryable({'status':status}))

class FastEvent:
    def __init__(self):self.flag=False
    def is_set(self):return self.flag
    def set(self):self.flag=True
    def wait(self,*a):return self.flag

class Recovery(unittest.TestCase):
    def test_parent_attempts_count_and_failed_lane_does_not_cancel_sibling(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);parent=root/'parent';p=parent/'learning/full-parent';p.mkdir(parents=True)
            old=root/'old';old.mkdir();(old/'progress.json').write_text(json.dumps({'decisions':[{'correct':True}]}))
            rows=[dict(trial_id='a',gpu=0,arm='memrsi'),dict(trial_id='b',gpu=1,arm='memrsi')]
            (p/'rows.json').write_text(json.dumps([dict(rows[0],status='cancelled',output=str(old))]))
            exp=module.Experiment(root/'run',(0,1),'orders','budget',FastEvent());seen=[]
            def episode(row,policy,dest):
                seen.append((row['trial_id'],dest.name));dest.mkdir(parents=True)
                if row['trial_id']=='a':
                    (dest/'model-errors.jsonl').write_text(json.dumps({'http_status':502})+'\n')
                    return dict(row,status='infrastructure_failure',output=str(dest))
                return dict(row,status='success',output=str(dest))
            exp.episode=episode
            with patch.object(module,'PARENT',parent):
                with self.assertRaisesRegex(RuntimeError,'technical_hold'):
                    exp.batch(rows,{'memrsi':'policy'},root/'full-parent',True)
            self.assertEqual(sorted(seen),[('a','attempt-02'),('a','attempt-03'),('b','attempt-01')])
            attempts=json.loads((root/'full-parent/attempts.json').read_text())
            self.assertEqual(len(attempts),4);self.assertTrue(attempts[0]['inherited'])
            self.assertFalse(exp.stop.is_set())
    def test_decision_failure_not_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);e=module.Experiment(root/'run',(0,),'o','b',FastEvent());seen=[]
            def episode(row,policy,dest):
                seen.append(1);return dict(row,status='decision_failure',output=str(dest))
            e.episode=episode
            result=e.batch([dict(trial_id='a',gpu=0,arm='memrsi')],{'memrsi':'p'},root/'full-candidate',True)
            self.assertEqual(len(seen),1);self.assertEqual(result[0]['status'],'decision_failure')
