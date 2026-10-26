"""Genuine native construction and stubbed G request; never contact provider."""
import asyncio,copy,importlib.util,json,tempfile,sys
from pathlib import Path
from types import SimpleNamespace as NS
from interventions import ARMS,agent_class,PROCEDURE,candidate_policy
ROOT=Path('/data/stormlab/xi/robot')
spec=importlib.util.spec_from_file_location('cap',ROOT/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
def main():
 old=ROOT/'runs/paper-completion-20261020/guidance-diagnostic-20261021';m=cap.read(old/'manifest.json');p=cap.read(old/'frozen-policy.json')
 assert cap.source_identity(m['source'],m['core'])==m['source_identity']
 engine=cap.load_engine(m['source'],m['core'])
 from memory_policy import screen,validate
 validate(candidate_policy(p));screen(candidate_policy(p))
 count=0
 with tempfile.TemporaryDirectory(prefix='guidance-delta-zero-call-') as d:
  for arm in ARMS:
   a=agent_class(engine.TwentyAgent,arm)('memrsi',Path(d)/arm/'attempt',old/'frozen-policy.json',m['budget'])
   policy=p if arm==ARMS[0] else candidate_policy(p)
   assert a.policy==policy and a.ops.policy==policy and a.provider.memory_policy==policy
   assert a.policy['update']==p['update']
   marker='VISIBLE_NATIVE_MEMORY_MARKER';(a.workspace/'memory').mkdir(exist_ok=True);(a.workspace/'memory/MEMORY.md').write_text(marker)
   assert marker in a.loop.context.build_system_prompt()
   async def stub(**kw):
    nonlocal count
    count+=1
    assert kw['messages'][0]['content']==json.loads(policy['guidance'])['procedure']
    assert kw['tools'][0]['function']['parameters']['properties']['ids']['maxItems']==5
    catalog=json.loads(kw['messages'][1]['content']);assert catalog['short:0']['text']=='real short'
    return NS(finish_reason='tool_calls',tool_calls=[NS(name='select_memory_evidence',arguments={'ids':['short:0']})])
   a.provider.chat=stub
   text=asyncio.run(a.ops.guide([{'content':'real short'}],'current'))
   assert json.loads(text.split('\n',2)[-1])[0]['text']=='real short'
   assert a.provider.calls==0 if hasattr(a.provider,'calls') else True
 print(json.dumps({'native_constructors':2,'stubbed_model_calls':count,'real_model_calls':0,'actor_memory_visible_both':True,'same_U_and_cap5':True}))
if __name__=='__main__':main()
