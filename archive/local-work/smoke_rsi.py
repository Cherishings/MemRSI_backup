import sys,asyncio,json,time
from pathlib import Path
base=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022')
sys.path[:0]=[str(base/'PhyAgentOS-core'),str(base/'portable-runtime-20261023/paos/worktrees/memrsi-bounded-v2_2')]
from model_provider import Provider,read_api_key,GATEWAY_URL,MODEL
async def main():
 p=Provider(base/'runtime-smoke/model-bridge-20261023')
 try:
  # One actual wire call through the RSI provider, without its experiment retry loop.
  r=await p._complete({'model':MODEL,'messages':[{'role':'user','content':'Reply exactly RSI_BRIDGE_OK.'}],'max_tokens':64})
  ok=r.finish_reason!='error' and 'RSI_BRIDGE_OK' in (r.content or '')
  print(json.dumps({'ok':ok,'provider':'RSI Provider','endpoint':GATEWAY_URL,'response':r.content,'finish_reason':r.finish_reason}))
  if not ok: raise SystemExit(1)
 finally: await p._client.close()
asyncio.run(main())
