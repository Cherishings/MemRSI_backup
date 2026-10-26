from pathlib import Path
import json, os, sys, shutil, datetime
os.umask(0o077)
b=Path('/media/disks/disk2/share/ext_songzhiying/PAOS-MemRSI-migration-20261022')
token=sys.stdin.read().strip()
assert len(token)>=32
for rel in ['paos/qwen-deploy/gpt-gateway-token','portable-runtime-20261023/paos/qwen-deploy/gpt-gateway-token']:
 p=b/rel
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and p.read_text().strip()!=token: shutil.copy2(p,p.with_suffix('.backup-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')))
 p.write_text(token+'\n');p.chmod(0o600)
p=Path.home()/'.PhyAgentOS/config.json'
d=json.loads(p.read_text()) if p.exists() else {}
if p.exists(): shutil.copy2(p,p.with_suffix('.json.backup-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')))
d.setdefault('agents',{}).setdefault('defaults',{}).update(model='gpt-5.6-luna',provider='custom')
d.setdefault('providers',{}).setdefault('custom',{}).update(apiKey=token,apiBase='http://127.0.0.1:19099/v1')
p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2)+'\n');p.chmod(0o600)
print('PAOS config and gateway-only credentials installed; upstream credentials remain local.')
