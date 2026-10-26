"""Replay-only semantic clock. Transport timers and wall-clock cost logs stay real."""
import importlib
from datetime import datetime,timedelta,timezone
from contextlib import contextmanager
BASE=datetime(2026,10,23,0,0,0)
MODULES=('PhyAgentOS.session.manager','PhyAgentOS.agent.context')
class ReplayDateTime(datetime):
 event=0
 @classmethod
 def now(cls,tz=None):
  value=BASE+timedelta(minutes=cls.event)
  return value if tz is None else value.replace(tzinfo=timezone.utc).astimezone(tz)
 @classmethod
 def utcnow(cls):return BASE+timedelta(minutes=cls.event)
def set_event(event):
 if type(event) is not int or event<0:raise ValueError('invalid_replay_event')
 ReplayDateTime.event=event
@contextmanager
def installed():
 previous=[]; loop=None; original_save=None
 try:
  set_event(0)
  for name in MODULES:
   module=importlib.import_module(name);previous.append((module,module.datetime));module.datetime=ReplayDateTime
  loop=importlib.import_module("PhyAgentOS.agent.loop").AgentLoop
  original_save=loop._save_turn
  def save_turn(self,session,messages,skip):
   before=len(session.messages)
   original_save(self,session,messages,skip)
   for entry in session.messages[before:]:entry["timestamp"]=ReplayDateTime.now().isoformat()
   session.updated_at=ReplayDateTime.now()
  loop._save_turn=save_turn
  yield
 finally:
  if original_save is not None:loop._save_turn=original_save
  for module,value in reversed(previous):module.datetime=value
