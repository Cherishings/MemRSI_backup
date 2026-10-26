"""Display title only; guarded entry point is safe for spawned imports."""
import runpy
import sys
from pathlib import Path

import setproctitle

setproctitle.setproctitle('robot')


def main():
    script = Path(sys.argv[1]).resolve()
    sys.argv = [str(script), *sys.argv[2:]]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main()
