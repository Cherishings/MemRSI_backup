"""Operational request queue waiting; keeps slots, prompts and counters unchanged."""
import asyncio,fcntl,os,time,json,hashlib
from pathlib import Path
from contextlib import asynccontextmanager

@asynccontextmanager
async def wait_for_slot(self):
 m=self.__class__._offline_transport_module
 started=time.monotonic();stream=None;slot=None;last_status=0.
 paths=[Path(m.MODEL_LOCK_PATH),Path(str(m.MODEL_LOCK_PATH)+'.slot-1')]
 try:
  while stream is None:
   for i,path in enumerate(paths):
    path.parent.mkdir(parents=True,exist_ok=True);handle=path.open('a')
    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:handle.close();continue
    stream=handle;slot=i;break
   if stream is None:
    now=time.monotonic()
    if now-last_status>=30:
     self.wait_clock.begin('shared_request_slot_wait',since=started)
     self._append('model-admission.jsonl',{'status':'waiting_same_request','pid':os.getpid(),'wait_seconds':now-started,'model_calls_before_admission':self.calls,'operational_patch':'offline-wait-20261020'})
     last_status=now
    await asyncio.sleep(0.25)
  self.wait_clock.end()
  self._append('model-admission.jsonl',{'status':'acquired','pid':os.getpid(),'slot':slot,'wait_seconds':time.monotonic()-started,'model_calls_before_admission':self.calls,'operational_patch':'offline-wait-20261020'})
  yield
 finally:
  if stream is not None:
   fcntl.flock(stream.fileno(),fcntl.LOCK_UN);stream.close();await asyncio.sleep(m.MODEL_RELEASE_YIELD)

def install(module):
 if getattr(module,'_offline_wait_installed',False):return
 module.Provider._offline_transport_module=module
 module.Provider._request_lease=wait_for_slot
 module._offline_wait_installed=True
