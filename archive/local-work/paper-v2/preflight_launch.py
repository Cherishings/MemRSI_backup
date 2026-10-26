import pathlib,sys,json,asyncio,subprocess,os,time
b=pathlib.Path('/data/songziying/paos-libero-20261023');r=b/'study-scope-v2';sys.path[:0]=[str(r/'code'),str(r/'code/runtime'),str(r/'source'),str(r/'paos-core')]
from run_case import verify
verify(r)
import runtime_adapter
runtime_adapter.configure(7,20517,str(r/'paos-core'))
import twenty_agent,method
async def main():
 parent=json.loads((r/'parent-policy.json').read_text())
 for arm in ('native','g_only','u_only','gu_parent','think_u'):
  policy=method.policy_for(parent,None,arm);cls=method.bind_agent_class(twenty_agent.TwentyAgent,arm,policy);out=r/'preflight'/arm;out.mkdir(parents=True)
  a=cls('native' if policy is None else 'memrsi',out,None if policy is None else r/'policies'/f'{arm}.json',r/'budget.json')
  assert a.provider.calls==0;await a.close()
asyncio.run(main())
from openpi_client.websocket_client_policy import WebsocketClientPolicy
client=WebsocketClientPolicy('127.0.0.1',20517);meta=client.get_server_metadata();assert meta['paired_sampling'] is True;client._ws.close()
(r/'preflight.json').write_text(json.dumps({'five_actor_interfaces':'passed','model_calls':0,'policy_metadata':meta,'time':time.time()},indent=2))
ids=subprocess.check_output(['docker','ps','-q','--filter','label=paos.owner=songziying-libero-20261023','--filter','name=songziying-paos-policy-'],text=True).split()
if ids:subprocess.run(['docker','stop','-t','10',*ids],check=True,stdout=subprocess.DEVNULL)
with (r/'queue.log').open('x') as f:p=subprocess.Popen([sys.executable,str(r/'code/queue_v2.py'),str(r)],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True,env=os.environ.copy())
(r/'queue-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}));print(json.dumps({'preflight':'passed','policy':'original CUDA/JAX through loopback tunnel','pid':p.pid,'root':str(r)}))
