"""One real source-state guidance probe and one recorded overflow compaction."""
import asyncio,json,datetime,urllib.request
from pathlib import Path
from feedback_learning import prepare,evaluate,read
from memory_policy import BASE
from memory_budget import BoundedStore,write_pair,pair
from token_accounting import memory_tokens
from model_provider import Provider
from replay import dump
async def run(out):
    out.mkdir(parents=True,exist_ok=False)
    with urllib.request.urlopen('http://127.0.0.1:19095/health',timeout=10) as f:health=json.load(f)
    if health.get('model')!='gpt-5.6-luna':raise RuntimeError('model_mismatch')
    dev,valid=prepare()
    assert {x['source'] for x in dev}.isdisjoint({x['source'] for x in valid})
    for x in dev+valid:assert x['current_event_id']-x['last_archived_event']==len(x['suffix'])+1
    r=await evaluate(dev[0],out/'source-probe',BASE)
    if r['status']!='answered':raise RuntimeError('source_probe_invalid')
    # Reuse a genuine over-capacity packing request from old boundary code.
    source=Path('/data/songziying/paos-libero-20261023/migration/portable-runtime-20261023/paos/results/paos-boundary-v1-20261011T051648Z/experiment')
    sample=None
    for p in sorted(source.rglob('model-trace.jsonl')):
        for line in p.read_text().splitlines():
            row=json.loads(line);request=row.get('request',{})
            if any(t.get('function',{}).get('name')=='pack_storage' for t in request.get('tools',[])):
                data=json.loads(request['messages'][1]['content'])
                sample=(p,data);break
        if sample:break
    if sample is None:raise RuntimeError('recorded_pack_request_missing')
    dest=out/'compression';dest.mkdir();provider=Provider(dest);audit=[]
    store=BoundedStore(dest,1024,lambda name,item:audit.append(dict(file=name,**item)))
    write_pair(store,(sample[1]['MEMORY.md'],sample[1]['HISTORY.md']))
    before=memory_tokens(*pair(store));assert before>1024
    try:ok=await store.fit(provider,'gpt-5.6-luna')
    finally:await provider._client.close()
    after=memory_tokens(*pair(store));dump(dest/'audit.json',audit)
    result={'status':'passed' if ok else 'failed','source_probe_status':r['status'],'source_probe_correct':r['correct'],
      'compression_source':str(sample[0]),'input_tokens':before,'output_tokens':after,'limit':1024,
      'compression_calls':provider.calls,'semantic_preservation_claim':False,'fixtures':len(dev)+len(valid)}
    dump(out/'result.json',result);print(json.dumps(result))
    if not ok or after>1024:raise RuntimeError('compression_preflight_failed')
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    asyncio.run(run(Path(a.output)))
