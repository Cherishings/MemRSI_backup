import json,os,signal,shutil,subprocess,time
from pathlib import Path
b=Path('/data/songziying/paos-libero-20261023')
a=json.loads((b/'development-launch.json').read_text());out=Path(a['job']['output'])
assert not (out/'calls.json').exists(), 'A model request has started; do not interrupt blindly'
p=Path('/proc')/str(a['pid'])/'cmdline'
if p.exists():
 assert str(b).encode() in p.read_bytes();assert os.getpgid(a['pid'])==a['pid']
 os.killpg(a['pid'],signal.SIGTERM)
# Stop only this deployment's physics workers; retain the policy service.
ids=subprocess.check_output(['docker','ps','-q','--filter','label=paos.owner=songziying-libero-20261023','--filter','name=songziying-paos-physics-'],text=True).split()
if ids:subprocess.run(['docker','stop','-t','10',*ids],check=True,stdout=subprocess.DEVNULL)
h=b/'technical-history'/str(time.time_ns());h.mkdir(parents=True)
shutil.move(str(out),h/'tokenizer-initialization-blocked')
shutil.move(str(b/'development-launch.json'),h/'development-launch.json')
log=b/'logs'/('development-'+a['job']['condition_id']+'.log');shutil.move(str(log),h/log.name)
(h/'repair.json').write_text(json.dumps({'reason':'Missing offline o200k_base tokenizer cache blocked before first model request','model_calls':0,'failure_preserved':True,'method_changed':False}))
p=b/'env.sh';s=p.read_text();line=f'export TIKTOKEN_CACHE_DIR={b}/migration/cache/tiktoken\n';p.write_text(s if line in s else s+line)
print('Stopped only own zero-call development processes; tokenizer cache configured')
