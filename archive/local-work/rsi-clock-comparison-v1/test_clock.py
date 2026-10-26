import unittest,sys,types
from unittest.mock import patch
from datetime import datetime,timezone
import replay_clock as c
class ClockTests(unittest.TestCase):
 def test_event_pairing(self):
  for i in [0,1,31,60]:
   c.set_event(i);a=c.ReplayDateTime.now();c.set_event(i);self.assertEqual(a,c.ReplayDateTime.now());self.assertEqual(a.year,2026)
 def test_monotonic_event(self):
  c.set_event(2);a=c.ReplayDateTime.now();c.set_event(3);self.assertEqual((c.ReplayDateTime.now()-a).total_seconds(),60)
 def test_restore_on_exception(self):
  modules={n:types.SimpleNamespace(datetime=datetime) for n in c.MODULES}
  modules['PhyAgentOS.agent.loop']=types.SimpleNamespace(AgentLoop=type('Loop',(),{'_save_turn':lambda *a:None}))
  with patch.object(c.importlib,'import_module',side_effect=modules.__getitem__):
   with self.assertRaises(RuntimeError):
    with c.installed():
     self.assertTrue(all(m.datetime is c.ReplayDateTime for n,m in modules.items() if n in c.MODULES));raise RuntimeError()
   self.assertTrue(all(m.datetime is datetime for n,m in modules.items() if n in c.MODULES))
 def test_invalid_and_timezone(self):
  for x in [-1,True,'1']:
   with self.assertRaises(ValueError):c.set_event(x)
  c.set_event(1);self.assertEqual(c.ReplayDateTime.now(timezone.utc).isoformat(),'2026-10-23T00:01:00+00:00')
if __name__=='__main__':unittest.main()
