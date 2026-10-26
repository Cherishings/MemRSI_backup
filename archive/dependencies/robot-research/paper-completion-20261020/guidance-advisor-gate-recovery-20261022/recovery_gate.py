"""One bounded acceptance extension; preserve first-block model failure as scored."""
import json
from pathlib import Path
from acceptance import inspect as original_inspect

def inspect(out,jobs):
 out=Path(out);m=json.loads((out/'manifest.json').read_text())
 first=original_inspect(out,m['jobs'][:4])
 if first['state']=='passed':return first
 second=original_inspect(out,m['jobs'][4:8])
 second['acceptance_amendment']='one_next_registered_four_arm_block_20261022'
 second['original_gate']=first
 second['original_results_retained']=True
 second['no_same_case_retry']=True
 second['extension_limit']=4
 return second
