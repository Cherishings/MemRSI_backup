from pathlib import Path
import tarfile,shutil,json,time,sys,subprocess,os
b=Path('/data/songziying/paos-libero-20261023');v=b/'physics-vendor';v.mkdir(exist_ok=True)
with tarfile.open(b/'archives/physics-extras.tar.gz') as t:t.extractall(v)
shutil.copy2(b/'docker_python.py',b/'migration/conda-envs/paos-libero-py38/bin/python')
p=b/'migration/conda-envs/paos-libero-py38/bin/python';p.chmod(0o755)
# Preserve the zero-model-call initialization failure before restarting this deployment check.
launch=json.loads((b/'development-launch.json').read_text());out=Path(launch['job']['output'])
result=json.loads((out/'result.json').read_text())
assert result['status']=='infrastructure_failure' and not result['decisions'] and not result['physical_executions']
h=b/'technical-history'/str(time.time_ns());h.mkdir(parents=True)
shutil.move(str(out),h/'failed-initialization')
shutil.move(str(b/'development-launch.json'),h/'development-launch.json')
log=b/'logs'/('development-'+launch['job']['condition_id']+'.log');shutil.move(str(log),h/log.name)
(h/'repair.json').write_text(json.dumps({'reason':'official evaluator imports missing imageio/tyro/tqdm in shared CPU base image; added isolated version-pinned dependency overlay','prior_failure_preserved':True,'method_changes':False,'model_calls_before_failure':0}))
print(launch['job']['condition_id'])
