import json
from datetime import datetime
from replay_clock import installed,set_event
from PhyAgentOS.session.manager import Session
from PhyAgentOS.agent.context import ContextBuilder
import PhyAgentOS.session.manager as sm
import PhyAgentOS.agent.context as ac
import PhyAgentOS.agent.loop as al
before=[m.datetime for m in (sm,ac)]
values=[]
for _ in range(2):
 with installed():
  set_event(31);s=Session(key='cli:paired');s.add_message('user','unchanged public event')
  al.AgentLoop._save_turn(al.AgentLoop.__new__(al.AgentLoop),s,[{'role':'assistant','content':'retained response'}],0)
  assert s.messages[-1]['timestamp']=='2026-10-23T00:31:00'
  values.append((s.messages,ContextBuilder._build_message_context('cli','paired')))
assert values[0]==values[1]
assert values[0][0][0]['timestamp']=='2026-10-23T00:31:00'
assert '2026-10-23 00:31' in values[0][1]
assert [m.datetime for m in (sm,ac)]==before
print(json.dumps({'real_component_checks':4,'model_calls':0,'restored':True}))
