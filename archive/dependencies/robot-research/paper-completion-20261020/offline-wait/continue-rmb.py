"""Continue the frozen study once audited technical attempt2 has a valid end."""
from pathlib import Path
import os,sys,json,time,subprocess,fcntl
R=Path('/data/stormlab/xi/robot');O=R/'runs/paper-completion-20261020/parallel-admission';H=Path(__file__).resolve().parent
sys.path.insert(0,str(H));from parallel_budget import alive,write,identity
import setproctitle;setproctitle.setproctitle('robot')
with (O/'rmb-continuation.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if (O/'rmb-study-launched.json').exists():raise SystemExit('already_launched')
 write(O/'rmb-continuation-supervisor.json',identity())
 legacy={'pid':737756,'start_ticks':'364112058'}
 while alive(legacy):time.sleep(15)
 case=R/'runs/official-memory-gpu56-20261020/rmbench/trajectories/development/5fd015e03e5258978c2f09104dcdf89224187cce23253e8e268139bb229140f0/2008'
 valid={'success','task_failure','protocol_failure','capacity_failure','budget_failure'}
 score=case/'scored-record.json'
 if not score.exists() or json.loads(score.read_text()).get('status') not in valid:
  write(O/'rmb-continuation-paused.json',{'reason':'attempt2_not_valid_terminal_manual_audit_no_third','time':time.time()});raise SystemExit(0)
 out=R/'runs/official-memory-accountresume-20261019/rmbench';cfg=json.loads((out/'resume-config.json').read_text())
 cmd=[sys.executable,str(H/'study-retry-map.py'),cfg['code'],'--benchmark','rmbench','--gpu','6','--policy',cfg['policy'],'--ledger',cfg['ledger'],'--qualification',cfg['qualification'],'--output',str(out)]
 with (O/'rmb-study.private.log').open('ab') as log:q=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 a=Path(f'/proc/{q.pid}/stat').read_text().rsplit(')',1)[1].split();row={'pid':q.pid,'start_ticks':a[19],'gpu':6,'parallel_admission':True,'time':time.time(),'argv':cmd,'technical_retry_source':str(case)}
 write(O/'rmb-study-launched.json',row);write(out/'coordinator.json',row)
