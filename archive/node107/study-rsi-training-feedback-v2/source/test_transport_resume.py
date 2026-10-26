import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from feedback_continue import pending_rows,main
from feedback_protocol import schedule
from memory_policy import BASE

class RetentionTests(unittest.TestCase):
    def test_keep_every_old_outcome_and_only_run_unstarted(self):
        planned=schedule();statuses=['decision_failure']*4+['success']+['infrastructure_failure']*3+['cancelled']*3
        old=[dict(row,status=status) for row,status in zip(planned,statuses)]
        pending=pending_rows(old,planned)
        self.assertEqual(len(pending),109)
        self.assertFalse({x['trial_id'] for x in old}&{x['trial_id'] for x in pending})
        self.assertEqual([x['status'] for x in old],statuses)
        with self.assertRaises(ValueError):pending_rows(old+old[:1],planned)
        with self.assertRaises(ValueError):pending_rows([dict(old[0],init=999)],planned)
        with self.assertRaises(ValueError):pending_rows([dict(old[0],status='running')],planned)
    def test_queue_carries_old_results_without_learning_and_executes_each_pending_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);parent=root/'old';parent.mkdir();(parent/'learning').mkdir()
            for name in ('selected-orders.json','budget.json','policy-freeze.json','manifest.json','learning-process.json'):
                (parent/name).write_text('{}')
            planned=schedule();old=[dict(x,status='decision_failure') for x in planned[:2]]
            pending=planned[2:6];completed=[]
            class Runner:
                def __init__(self,*args,**kwargs):pass
                def acquire(self,state):state('starting_policy')
                def track(self,child,kind):return {'pid':child.pid,'start_ticks':'1'}
                def stop_owned(self,child):pass
                def release_process(self,child):pass
                def close(self):pass
            class Child:
                pid=12345
                def poll(self):return 0
            def popen(cmd,**kwargs):
                self.assertIn('feedback_workflow.py',cmd[1]);out=Path(cmd[cmd.index('--output')+1]);out.mkdir()
                (out/'result.json').write_text(json.dumps({'status':'success','correct_checkpoints':7,'answered_checkpoints':7,'reached_checkpoints':7}))
                completed.append(out);return Child()
            args=SimpleNamespace(output=str(root/'new'),parent=str(parent),probe='offline')
            with patch('feedback_continue.inspect',return_value=(old.copy(),pending,BASE,{})),\
                 patch('feedback_continue.PhysicalRunner',Runner),patch('feedback_continue.subprocess.Popen',popen),\
                 patch('feedback_continue.signal.signal'):
                main(args)
            rows=json.loads((root/'new/rows.json').read_text())
            self.assertEqual(len(rows),6);self.assertEqual(rows[:2],old)
            self.assertEqual(len(completed),4);self.assertEqual(len(set(completed)),4)
            self.assertTrue((root/'new/learning').is_symlink())
            self.assertEqual(json.loads((root/'new/manifest.json').read_text())['learning_rerun'],False)

if __name__=='__main__':unittest.main()
