import json,hashlib,shutil,time,sys
from pathlib import Path
r=Path(sys.argv[1]);incoming=Path(sys.argv[2])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
stamp=str(time.time_ns());history=r/'runtime-repair-history'/stamp;history.mkdir(parents=True)
files=['source/network_wait.py','code/learn.py','registration.json','registration.sha256','learning/registration.json']
for name in files:
 p=r/name
 if p.exists():
  dest=history/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
network=r/'source/network_wait.py';s=network.read_text()
marker="def transient(error):\n"
if "error.get('code') == 'gateway_busy'" not in s:
 s=s.replace(marker,marker+"    if (error.get('code') == 'gateway_busy' and error.get('stage') == 'admission'\n            and error.get('retryable') is True and error.get('output_started') is False\n            and error.get('http_status') in (429,502,503)):\n        return True\n")
 network.write_text(s)
old=sha(r/'code/learn.py');shutil.copy2(incoming,r/'code/learn.py');new=sha(r/'code/learn.py')
a={'time':time.time(),'kind':'transport_reliability_only','old_learner_sha256':old,'new_learner_sha256':new,'reason':'Single-wire learner override bypassed existing network waiting; observed buffered 502 ConnectionError and explicit gateway_busy admission refusal terminated validation. Restore identical-request wait/retry and exclude outage duration from active replay timeout.','model_policy_changed':False,'old_results_preserved':True,'old_failed_experiments_automatically_retried':False}
p=r/'registration.json';d=json.loads(p.read_text());d['frozen_files']['code/learn.py']=new;d['frozen_files']['source/network_wait.py']=sha(network);d.setdefault('administrative_amendments',[]).append(a);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');(r/'registration.sha256').write_text(sha(p)+'\n')
p=r/'learning/registration.json'
if p.exists():
 d=json.loads(p.read_text());d['learner_sha256']=new;d['network_retries']='identical buffered request after transport interruption; no experiment resampling';p.write_text(json.dumps(d,indent=2)+'\n')
(history/'amendment.json').write_text(json.dumps(a,indent=2)+'\n');print(json.dumps(a))
