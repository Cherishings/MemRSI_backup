"""Verified pi05 loader plus the frozen common-random-number policy wrapper."""
import runpy
import sys
from libero_runtime import Paths


if __name__ == '__main__':
    paths = Paths()
    for path in reversed(paths.pythonpath()):
        if path not in sys.path:
            sys.path.insert(0, path)
    # Original server already accepts --port and --checkpoint. It uses the same
    # create_trained_policy(pi05_libero, checkpoint) as policy_loopback_migration.
    runpy.run_path(str(paths.source / 'serve_paired_policy.py'), run_name='__main__')
