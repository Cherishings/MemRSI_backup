import importlib.metadata as m,tarfile,pathlib
site=pathlib.Path(m.distribution('imageio').locate_file('')).resolve()
roots=['imageio','imageio-ffmpeg','tyro','tqdm','docstring-parser','rich','shtab','typeguard','typing-extensions','markdown-it-py','mdurl','Pygments','eval-type-backport','importlib-metadata','zipp']
with tarfile.open('work/libero-repair/physics-extras.tar.gz','w:gz',compresslevel=1) as t:
 seen=set()
 for name in roots:
  d=m.distribution(name)
  for f in d.files or []:
   p=pathlib.Path(d.locate_file(f)).resolve()
   if not p.is_file() or site not in p.parents or p.suffix=='.pyc' or p in seen:continue
   t.add(p,arcname=str(p.relative_to(site)));seen.add(p)
  print(name,d.version)
