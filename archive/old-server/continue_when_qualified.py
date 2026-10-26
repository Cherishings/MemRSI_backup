import json,os,subprocess,sys,time
from pathlib import Path
r=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-RSI-20261023-gpu67-learn48k-runtimefix')
py='/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/conda-envs/paos-agent/bin/python'
sys.path.insert(0,str(r/'code'));from run_case import verify,write
verify(r)
old=r.with_name('PAOS-LIBERO-RSI-20261023-gpu67')
wrapper=(old/'runtime-control/foreground_runner.py').read_text().replace(str(old),str(r))
wrapper=wrapper.replace("str(R/'code/pipeline.py')","str(R/'runtime-control/final_only.py')")
(r/'runtime-control/final_wrapper.py').write_text(wrapper)
(r/'runtime-control/final_only.py').write_text('''import sys,time,json,traceback
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
''')
write(r/'continuation.json',{'phase':'waiting_for_registered_learning','gpus':[6,7],'condition':'accepted automatic candidate only','test_feedback_to_learning':False,'automatic_retry':False,'time':time.time()})
end=time.monotonic()+96*3600
while time.monotonic()<end:
 if (r/'learning/report.json').exists():
  report=json.loads((r/'learning/report.json').read_text())
  if not report['accepted']:
   write(r/'continuation.json',{'phase':'development_needed','reason':'no_qualified_update','automatic_final_test':False,'time':time.time()});break
  write(r/'continuation.json',{'phase':'starting_frozen_physical_comparison','time':time.time()})
  with (r/'runtime-control/final-wrapper.log').open('x') as log:
   result=subprocess.run([py,str(r/'runtime-control/final_wrapper.py')],stdout=log,stderr=log)
  write(r/'continuation.json',{'phase':'physical_comparison_finished' if result.returncode==0 else 'physical_comparison_blocked','exit_code':result.returncode,'time':time.time()});break
 state=json.loads((r/'status.json').read_text())
 if state['phase']=='blocked':
  write(r/'continuation.json',{'phase':'learning_blocked','time':time.time(),'automatic_retry':False});break
 time.sleep(30)
else:write(r/'continuation.json',{'phase':'timeout','time':time.time()})
