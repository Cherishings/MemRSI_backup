import subprocess,tarfile,json,pathlib
image='phyagentos-openpi-hcu:pi05-v016-dtk2604-20260901'
r=pathlib.Path('/data/songziying/paos-libero-20261023/archives')
p=subprocess.Popen(['docker','save',image],stdout=subprocess.PIPE)
with tarfile.open(fileobj=p.stdout,mode='r|') as src, tarfile.open(r/'pi05-incremental.tar.gz','w:gz',compresslevel=1) as dst:
 for member in src:
  # Both hosts have the same base layers. Retain metadata and layers below 2GB.
  if member.size<2_000_000_000:
   dst.addfile(member,src.extractfile(member) if member.isfile() else None)
assert p.wait()==0
print('saved',flush=True)
