import asyncio,importlib.util,json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from interventions import ARMS,agent_class,policy_for
R=Path('/data/share/ext_songzhiying/PAOS-MemRSI-migration-20261022/portable-runtime-20261023/robot');s=importlib.util.spec_from_file_location('cap',R/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(s);s.loader.exec_module(cap)
def main():
 old=R/'runs/paper-completion-20261020/gu-repair-r2-20261022';m=cap.read(old/'manifest.json');parent=cap.read(old/'frozen-policy.json');sys.path.insert(0,m['core']);assert cap.source_identity(m['source'],m['core'])==m['source_identity'];engine=cap.load_engine(m['source'],m['core'])
 from memory_policy import validate,screen,archive_request
 from token_accounting import request_tokens
 captured={};budgets=[]
 with tempfile.TemporaryDirectory(prefix='advisor-study-zero-') as tmp:
  for arm in ARMS:
   policy=policy_for(parent,arm);validate(policy);screen(policy)
   a=agent_class(engine.TwentyAgent,arm)('memrsi',Path(tmp)/arm/'attempt',old/'frozen-policy.json',m['budget']);assert a.policy==policy and a.provider.memory_policy==policy
   (a.workspace/'memory/MEMORY.md').write_text('PUBLIC_MEMORY_MARKER');assert 'PUBLIC_MEMORY_MARKER' in a.loop.context.build_system_prompt()
   request={'messages':[{'role':'system','content':'native archive'}],'tools':[{'function':{'name':'save_memory'}}]};assert archive_request(request,policy) is not request
   async def stub(**kw):
    captured[arm]=kw
    if arm=='evidence_u1':return NS(finish_reason='tool_calls',tool_calls=[NS(name='select_memory_evidence',arguments={'ids':['short:0']})])
    return NS(finish_reason='tool_calls',tool_calls=[NS(name='report_advice',arguments={'recommendation':'','basis_ids':[],'uncertainty':'No action assumed'})])
   a.provider.chat=stub
   if arm!='off_u1':
    text=asyncio.run(a.ops.guide([{'role':'user','content':'PUBLIC_SHORT_MARKER'}],'current'));assert isinstance(text,str)
    n=request_tokens(captured[arm]['messages'],captured[arm]['tools']);assert n<=a.provider.budget['active_input_tokens'];budgets.append({'arm':arm,'fixture_input_tokens':n})
   else:assert a.ops is None
   a.pending_dispatch={'decision_event':1,'submitted_skill':'public_skill'};asyncio.run(a.observe_only('Actual execution receipt: {"success": false}'));assert a.pending_dispatch is None
   assert a.provider.calls==0
 assert captured['advisor_u1']['messages'][1]==captured['deliberation_u1']['messages'][1]
 assert captured['advisor_u1']['tools']==captured['deliberation_u1']['tools']
 print(json.dumps({'native_constructors':4,'real_model_calls':0,'physical_calls':0,'native_MEMORY_visible_all':True,'same_U_all':True,'extra_pass_inputs_schema_equal':True,'fixture_budgets':budgets}))
if __name__=='__main__':main()
