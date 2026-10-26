import sys,time,json,traceback
from pathlib import Path
R=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(R/'code'),str(R/'code/runtime')]
import pipeline as p
p.START=time.monotonic();p.m=p.verify(R)
try:
 report=json.loads((R/'learning/report.json').read_text());assert report['accepted']
 selected=json.loads((R/'learning/selected-policy.json').read_text())
 policies=p.freeze_final(selected)
 rows=p.batch(p.make_jobs(p.m['test_conditions'],policies,'final'),'final')
 import analyze
 analyze.main(R)
 p.status('completed',completed=len(rows))
except Exception as e:
 p.status('blocked',reason=str(e));traceback.print_exc();sys.exit(2)
finally:p.cleanup()
