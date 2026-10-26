import asyncio,importlib.util,json,tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from interventions import ARMS,agent_class,policy_for
R=Path('/data/stormlab/xi/robot');s=importlib.util.spec_from_file_location('cap',R/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(s);s.loader.exec_module(cap)
def main():
 old=R/'runs/paper-completion-20261020/guidance-diagnostic-20261021';m=cap.read(old/'manifest.json');parent=cap.read(old/'frozen-policy.json');assert cap.source_identity(m['source'],m['core'])==m['source_identity'];engine=cap.load_engine(m['source'],m['core'])
 from memory_policy import validate,screen,archive_request
 with tempfile.TemporaryDirectory(prefix='gu-zero-call-') as tmp:
  for arm in ARMS:
   policy=policy_for(parent,arm);validate(policy);screen(policy)
   a=agent_class(engine.TwentyAgent,arm)('memrsi',Path(tmp)/arm/'attempt',old/'frozen-policy.json',m['budget']);assert a.policy==policy and a.provider.memory_policy==policy
   (a.workspace/'memory').mkdir(exist_ok=True);(a.workspace/'memory/MEMORY.md').write_text('PUBLIC_MEMORY_MARKER');assert 'PUBLIC_MEMORY_MARKER' in a.loop.context.build_system_prompt()
   request={'messages':[{'role':'system','content':'native archive'}],'tools':[{'function':{'name':'save_memory'}}]};req=archive_request(request,policy);assert (req is not request)==arm.endswith('u1')
   async def stub(**kw):
    catalog=json.loads(kw['messages'][1]['content']);assert 'PUBLIC_SHORT_MARKER' in catalog['short:0']['text'];assert kw['tools'][0]['function']['parameters']['properties']['ids']['maxItems']==5
    return NS(finish_reason='tool_calls',tool_calls=[NS(name='select_memory_evidence',arguments={'ids':['short:0']})])
   a.provider.chat=stub
   if arm.startswith('g1'):
    text=asyncio.run(a.ops.guide([{'content':'PUBLIC_SHORT_MARKER'}],'current'));assert 'PUBLIC_SHORT_MARKER' in text
   else:assert a.ops is None
   a.pending_dispatch={'decision_event':1,'submitted_skill':'public_skill'};asyncio.run(a.observe_only('Actual execution receipt: {"success": false}'));session=a.loop.sessions.get_or_create(a.session_key);assert 'Execution correlation (dispatcher metadata)' in session.messages[-1]['content'];assert a.pending_dispatch is None
   assert a.provider.calls==0
 print(json.dumps({'actual_native_constructors':4,'real_model_calls':0,'native_MEMORY_visible_all':True,'exact_G_off_on_verified':True,'native_or_custom_U_request_verified':True,'cap5_and_actual_S_forwarding':True}))
if __name__=='__main__':main()
