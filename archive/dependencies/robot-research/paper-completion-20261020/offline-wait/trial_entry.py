"""Keep original trial implementation and source hashes; alter admission only."""
import sys,importlib.util
from pathlib import Path
code=Path(sys.argv.pop(1));sys.path.insert(0,str(code))
spec=importlib.util.spec_from_file_location('run_trial',code/'run_trial.py');rt=importlib.util.module_from_spec(spec);spec.loader.exec_module(rt)
from parallel_budget import install_admission
install_admission(rt)
rt.main()
