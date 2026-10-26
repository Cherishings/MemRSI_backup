import asyncio,json,sys
from pathlib import Path
r=Path(sys.argv[1]);sys.path[:0]=[str(r/'code'),str(r/'source'),str(r/'paos-core')]
import twenty_agent,method,memory_design,memory_policy
async def main():
 for name,policy in json.loads((r/'preflight-policies.json').read_text()).items():
  memory_policy.validate(policy);memory_design.update_instruction(policy['update'])
  method.guidance_procedure(policy)
  p=r/'runtime-control/preflight'/name;p.mkdir(parents=True,exist_ok=True)
  f=p/'policy.json';f.write_text(json.dumps(policy))
  cls=method.bind_agent_class(twenty_agent.TwentyAgent,'gu_parent',policy)
  a=cls('memrsi',p,f,r/'budget.json')
  assert a.provider.calls==0
  await a.close()
 print('All parent/G/U/joint real actor initializations and update parsers passed; model calls=0',flush=True)
asyncio.run(main())
