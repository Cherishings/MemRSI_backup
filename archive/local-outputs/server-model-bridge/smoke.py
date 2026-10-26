"""Run on the new server: one bounded PAOS provider request, no robot actions."""
import asyncio, json, sys, time
from pathlib import Path
BASE=Path('/media/disks/disk2/share/ext_songzhiying/PAOS-MemRSI-migration-20261022')
sys.path.insert(0,str(BASE/'PhyAgentOS-core'))
from PhyAgentOS.config.loader import load_config
from PhyAgentOS.providers.custom_provider import CustomProvider
async def main():
    config=load_config()
    assert config.get_provider_name()=='custom'
    assert config.get_api_base()=='http://127.0.0.1:19099/v1'
    provider=CustomProvider(api_key=config.get_api_key(),api_base=config.get_api_base(),default_model=config.agents.defaults.model,timeout_s=220)
    provider._client.max_retries=0
    start=time.monotonic()
    try:
        result=await provider.chat(messages=[{'role':'user','content':'Reply with exactly PAOS_BRIDGE_OK.'}],max_tokens=64,temperature=0)
        report={'ok':result.finish_reason!='error' and 'PAOS_BRIDGE_OK' in (result.content or ''),'model':provider.default_model,'response':result.content,'finish_reason':result.finish_reason,'elapsed_seconds':round(time.monotonic()-start,2)}
        print(json.dumps(report))
        if not report['ok']: raise SystemExit(1)
    finally:
        await provider._client.close()
asyncio.run(main())
