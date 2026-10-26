import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from run_check import acquire, lock_name


class LeaseTests(unittest.TestCase):
    def test_live_experiment_prevents_start(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'lease'
            with path.open('a') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                memory = Mock(return_value=0)
                with self.assertRaisesRegex(RuntimeError, 'gpu_busy'):
                    acquire(path, False, memory)
                memory.assert_not_called()

    def test_wait_does_not_steal_lock_and_resumes_when_released(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'lease'
            with path.open('a') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                def release(_):
                    fcntl.flock(owner, fcntl.LOCK_UN)
                with acquire(path, True, lambda: 0, sleep=release):
                    with path.open('a') as contender:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_noncooperating_gpu_user_is_respected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'lease'
            with self.assertRaisesRegex(RuntimeError, 'gpu_busy'):
                acquire(path, False, lambda: 8000)
            with path.open('a') as other:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_lock_names_match_current_experiments(self):
        self.assertEqual([lock_name(g) for g in (0, 1, 2)],
                         ['robot-run.lock', 'gpt-gpu1-run.lock', 'gpt-gpu2-run.lock'])


if __name__ == '__main__':
    unittest.main()
