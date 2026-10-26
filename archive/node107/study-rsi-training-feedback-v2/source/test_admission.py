"""Admission/launch lifecycle tests; never contact model services or GPUs."""
import contextlib
import fcntl
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import admission_wait as admission
import launch


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class AdmissionTests(unittest.TestCase):
    def predecessor(self, root, status='completed'):
        write(root/'coordinator.json', {'pid':101, 'start_ticks':'1001'})
        write(root/'progress.json', {'status':status, 'terminal':32 if status=='completed' else 30,
            'planned':32, 'active':{'0':{'worker':{'pid':202,'start_ticks':'2002'}}}})

    def test_dead_coordinator_does_not_hide_live_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.predecessor(root)
            with patch.object(admission,'alive',side_effect=lambda r:r['pid']==202):
                state=admission.previous_state(root)
            self.assertEqual(state['live_processes'],[{'pid':202,'start_ticks':'2002'}])

    def test_live_legacy_worker_blocks_admission_until_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.predecessor(root)
            with patch.object(admission,'alive',side_effect=lambda r:r['pid']==202):
                with self.assertRaisesRegex(RuntimeError,'admission_wait_budget_exhausted'):
                    admission.wait_previous(root,root/'admission.json',wait_seconds=-1,poll_seconds=0,quiet_seconds=0)

    def test_dead_incomplete_predecessor_is_not_treated_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.predecessor(root,'running')
            with patch.object(admission,'alive',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'previous_queue_incomplete'):
                    admission.wait_previous(root,root/'admission.json',poll_seconds=0,quiet_seconds=0)

    def test_admission_failure_releases_structured_failure_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            args=types.SimpleNamespace(source=str(root/'old'),status=str(root/'admission.json'),
                failure=str(root/'evolution/failure.json'),command=['/does/not/exist'])
            with patch.object(admission,'wait_previous',side_effect=RuntimeError('admission_wait_budget_exhausted')),patch.object(admission.os,'execv') as execute:
                with self.assertRaisesRegex(RuntimeError,'admission_wait_budget_exhausted'):admission.main(args)
            execute.assert_not_called()
            self.assertEqual(json.loads((root/'evolution/failure.json').read_text())['stage'],'admission')

    def test_success_does_not_precreate_evolution_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            args=types.SimpleNamespace(source=str(root/'old'),status=str(root/'admission.json'),
                failure=str(root/'evolution/failure.json'),command=['/usr/bin/python3','evolution.py'])
            def execute(*args):
                self.assertFalse((root/'evolution').exists())
                raise SystemExit(0)  # successful exec never returns
            with patch.object(admission,'wait_previous'),patch.object(admission.os,'execv',side_effect=execute):
                with self.assertRaises(SystemExit):admission.main(args)
            self.assertFalse((root/'evolution').exists())

    def test_exec_error_creates_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            args=types.SimpleNamespace(source='old',status=str(root/'admission.json'),failure=None,command=['missing'])
            with patch.object(admission,'wait_previous'),patch.object(admission.os,'execv',side_effect=OSError()):
                with self.assertRaisesRegex(RuntimeError,'admission_dependency_or_exec_failure'):admission.main(args)
            self.assertTrue((root/'evolution/failure.json').exists())

    def test_pid_reuse_fails_start_tick_identity(self):
        with patch.object(admission,'identity',return_value={'pid':101,'start_ticks':'9999'}):
            self.assertFalse(admission.alive({'pid':101,'start_ticks':'1001'}))


class LaunchTests(unittest.TestCase):
    def test_inherited_lease_survives_launcher_close_and_exec(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);handle=(root/'pipeline.lock').open('a')
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            script="import os,sys;os.execv(sys.executable,[sys.executable,'-c','import time;print(\"ready\",flush=True);time.sleep(20)'])"
            child=subprocess.Popen([sys.executable,'-c',script],pass_fds=(handle.fileno(),),start_new_session=True,stdout=subprocess.PIPE,text=True)
            handle.close()
            try:
                self.assertEqual(child.stdout.readline().strip(),'ready')
                self.assertTrue(launch.pipeline_lease_live(root))
            finally:
                child.terminate();child.wait(timeout=5)
                child.stdout.close()
            self.assertFalse(launch.pipeline_lease_live(root))

    def test_orphan_worker_detected_when_both_coordinators_dead(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            write(root/'physical/progress.json',{'active':{'1':{'worker':{'pid':303,'start_ticks':'3003'}}}})
            record={'processes':{'physical':{'pid':101,'start_ticks':'1001'}}}
            with patch.object(launch,'alive',side_effect=lambda r:r['pid']==303):
                self.assertEqual(launch.previous_activity(root,record),[{'pid':303,'start_ticks':'3003'}])

    def test_second_spawn_failure_has_registered_first_and_cleans_only_own_child(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);base=root/'base';code=root/'code'
            (base/'qwen-deploy').mkdir(parents=True);(base/'results').mkdir();code.mkdir()
            write(code/'pristine-core-manifest.json',{'core_sha256':{},'mismatches':[]})
            child=types.SimpleNamespace(pid=404,poll=lambda:None)
            calls=[]
            def popen(*args,**kwargs):
                pointer=base/'qwen-deploy/latest-memrsi-coupled.txt'
                output=Path(pointer.read_text().strip())
                record=json.loads((output/'launch.json').read_text())
                self.assertIn('pass_fds',kwargs)
                if not calls:
                    self.assertEqual(record['processes'],{})
                    self.assertTrue(launch.pipeline_lease_live(output))
                    calls.append('first');return child
                self.assertEqual(record['processes']['evolution'],{'pid':404,'start_ticks':'4004'})
                raise OSError('synthetic spawn failure')
            with patch.object(launch,'BASE',base),patch.object(launch,'ROOT',code),patch.object(launch.subprocess,'Popen',side_effect=popen),patch.object(launch,'identity',return_value={'pid':404,'start_ticks':'4004'}),patch.object(launch,'alive',return_value=True),patch.object(launch,'stop_group') as stop:
                with self.assertRaisesRegex(RuntimeError,'launch_registration_or_spawn_failure'):launch.main()
            stop.assert_called_once_with(child)
            output=Path((base/'qwen-deploy/latest-memrsi-coupled.txt').read_text().strip())
            self.assertEqual(json.loads((output/'launch.json').read_text())['status'],'launch_failed')

    def test_incomplete_same_version_cannot_reset_budget_in_new_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'qwen-deploy').mkdir();old=base/'results/memrsi-coupled-v1_1-old'
            write(old/'launch.json',{'version':launch.VERSION,'status':'running','processes':{}})
            with patch.object(launch,'BASE',base),patch.object(launch.subprocess,'Popen') as popen,contextlib.redirect_stdout(io.StringIO()) as stdout:
                launch.main()
            popen.assert_not_called()
            self.assertEqual(json.loads(stdout.getvalue())['status'],'existing_incomplete_pipeline')


if __name__=='__main__':unittest.main()
