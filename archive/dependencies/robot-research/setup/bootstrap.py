"""Display title only: this does not hide the process or its files."""
import sys,runpy
from pathlib import Path
import setproctitle
setproctitle.setproctitle('robot')
script=Path(sys.argv[1]).resolve()
sys.argv=[str(script),*sys.argv[2:]]
sys.path.insert(0,str(script.parent))
runpy.run_path(str(script),run_name='__main__')
