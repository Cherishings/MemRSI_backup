from pathlib import Path
import json,sys,time,urllib.request
b=Path('/data/songziying/paos-libero-20261023')
sys.path[:0]=[str(b/'study/paos-core'),str(b/'study/source'),str(b/'study/code')]
import PhyAgentOS,twenty_agent,method
key=(b/'migration/portable-runtime-20261023/paos/qwen-deploy/gpt-gateway-token').read_text().strip()
req=urllib.request.Request('http://127.0.0.1:19098/v1/chat/completions',data=json.dumps({'model':'gpt-5.6-luna','messages':[{'role':'user','content':'Reply with exactly OK.'}],'max_tokens':32,'temperature':0}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=180) as r:body=json.load(r)
result={'time':time.time(),'paos_imports':'passed','model':body.get('model'),'response':body['choices'][0]['message'].get('content'),'server_to_local_gateway':True}
(b/'gateway-check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
