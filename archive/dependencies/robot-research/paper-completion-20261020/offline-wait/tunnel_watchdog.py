"""Kill only this dedicated forwarding session after client heartbeat loss."""
import os,signal,select,sys,time,json
from pathlib import Path
idle=float(sys.argv[1]) if len(sys.argv)>1 else 90.0
parent=os.getppid();p=Path('/proc')/str(parent)
identity=p.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]
assert p.stat().st_uid==os.getuid() and p.joinpath('comm').read_text().strip()=='sshd'
last=time.monotonic()
try:
 while True:
  ready,_,_=select.select([sys.stdin],[],[],max(0,idle-(time.monotonic()-last)))
  if not ready:break
  data=os.read(sys.stdin.fileno(),4096)
  if not data:break
  if any(x!=b'heartbeat' for x in data.splitlines()):break
  last=time.monotonic()
finally:
 try:
  a=p.joinpath('stat').read_text().rsplit(')',1)[1].split()
  if a[19]==identity and p.stat().st_uid==os.getuid() and p.joinpath('comm').read_text().strip()=='sshd':os.kill(parent,signal.SIGTERM)
 except ProcessLookupError:pass
