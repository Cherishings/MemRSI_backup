import argparse,asyncio,json,os,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--job',required=True);a=p.parse_args();r=Path(a.root);j=json.loads(Path(a.job).read_text())
sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'source'),str(r/'paos-core')]
from run_case import verify,write
m=verify(r);allocation=json.loads((r/'allocation.json').read_text())
assert j['condition_id'] in allocation['allowed_condition_ids']
assert j['arm'] in ('native','g_only','u_only','gu_parent','think_u')
assert j in json.loads((r/'development-schedule.json').read_text())
out=Path(j['output']);assert not out.exists()
os.environ.update(PAOS_LIBERO_SOURCE=str(r/'source'),PAOS_CORE_ROOT=str(r/'paos-core'))
import runtime_adapter
runtime_adapter.configure(7,20517,str(r/'paos-core'))
import feedback_workflow,twenty_agent,twenty_protocol,planning,method,model_provider
feedback_workflow.plan=planning.bind_registered_plan(twenty_protocol.plan,m['all_histories'])
parent=json.loads((r/'parent-policy.json').read_text());policy=method.policy_for(parent,parent,j['arm'])
twenty_agent.TwentyAgent=method.bind_agent_class(twenty_agent.TwentyAgent,j['arm'],policy)
model_provider.CALL_LIMIT=m['call_limit_per_case']
from types import SimpleNamespace
args=SimpleNamespace(output=str(out),orders=str(r/'orders.json'),port=20517,init=j['init'],variant=j['variant'],history=j['history'],arm='native' if policy is None else 'memrsi',budget=str(r/'budget.json'),memory_policy=None if policy is None else str(r/'policies'/f"{j['arm']}.json"))
result=asyncio.run(feedback_workflow.run(args));result.update(registered_arm=j['arm'],condition_id=j['condition_id'],scope='development only; manually improved parent, not RSI result',registration_sha256=(r/'registration.sha256').read_text().strip(),finished_at=time.time())
write(out/'result.json',result)
