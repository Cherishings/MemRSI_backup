import pathlib,json,shutil,tarfile,hashlib,os,sys,subprocess,time
b=pathlib.Path('/data/songziying/paos-libero-20261023');src=b/'study-rsi-v4-sources';r=b/'study-rsi-v4-learning'
assert not r.exists(),'Do not duplicate learner'
assert json.loads((src/'queue-status.json').read_text())['phase']=='development_complete'
archive=b/'rsi-v4-incoming/rsi-v4-source-export.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='9045b126e05b70ec912a4615c6c1c7d82d638dc052695aee96a8f11788a2a517'
r.mkdir();imp=r/'import108';imp.mkdir()
with tarfile.open(archive) as t:
 for m in t.getmembers():
  assert m.isfile() and not pathlib.Path(m.name).is_absolute() and '..' not in pathlib.Path(m.name).parts
 t.extractall(imp)
for name in ['code','source']:shutil.copytree(src/name,r/name,ignore=shutil.ignore_patterns('__pycache__'))
(r/'paos-core').symlink_to(src/'paos-core',target_is_directory=True)
for name in ['parent-policy.json','budget.json']:shutil.copy2(src/name,r/name)
shutil.copy2(b/'rsi-v4-incoming/learn.py',r/'code/learn.py');shutil.copy2(b/'rsi-v4-incoming/erratum.json',r/'learner-erratum.json')
ids=[]
for name in ['training-sources.json','validation-sources.json']:
 local=json.loads((src/name).read_text());remote=json.loads((imp/name).read_text())
 for row in remote:row['output']=str(imp/'cases'/row['id'])
 rows=sorted(local+remote,key=lambda x:x['id']);assert len(rows)==(8 if name.startswith('training') else 4)
 for row in rows:assert (pathlib.Path(row['output'])/'result.json').exists()
 ids.extend(x['id'] for x in rows);(r/name).write_text(json.dumps(rows,indent=2)+'\n')
assert len(ids)==len(set(ids))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
reg={'registered_at':time.time(),'phase':'automatic_G_U_proposals_and_controlled_replay','single_controller_node':'107','final_test_started':False,'manual_candidate_edits_allowed':False,'max_proposals_per_operator':1,'import108_archive_sha256':sha(archive),'parent_sha256':sha(r/'parent-policy.json'),'training_manifest_sha256':sha(r/'training-sources.json'),'validation_manifest_sha256':sha(r/'validation-sources.json'),'files':{str(p.relative_to(r)):sha(p) for folder in ['code','source'] for p in (r/folder).rglob('*.py')},'failure_policy':'retain all rejected proposals, failed replays and unknown costs; no resampling to obtain success'}
(r/'controller-registration.json').write_text(json.dumps(reg,indent=2)+'\n')
env=os.environ.copy();env['PAOS_LIBERO_SOURCE']=str(r/'source');env['PAOS_CORE_ROOT']=str(r/'paos-core');env['PYTHONPATH']=':'.join([str(r/'code'),str(r/'code/runtime'),str(r/'code/protocol'),str(r/'source'),str(r/'paos-core'),env.get('PYTHONPATH','')])
args=[sys.executable,str(r/'code/learn.py'),'--root',str(r),'--source',str(r/'source'),'--core',str(r/'paos-core'),'--train-manifest',str(r/'training-sources.json'),'--validation-manifest',str(r/'validation-sources.json'),'--parent-policy',str(r/'parent-policy.json'),'--budget',str(r/'budget.json')]
with (r/'controller.log').open('x') as log:p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,start_new_session=True)
state={'root':str(r),'pid':p.pid,'time':time.time(),'phase':'automatic_learning','node':'107'};(r/'controller-launch.json').write_text(json.dumps(state));(b/'active-learning.json').write_text(json.dumps(state));print(json.dumps(state))
