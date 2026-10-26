"""Native constructors and captured requests only; no provider/model/physical calls."""
import asyncio, importlib.util, json, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from advisor import Advisor
R=Path('/data/stormlab/xi/robot')
spec=importlib.util.spec_from_file_location('cap',R/'paper-supplement-20261018/capacity_robustness.py');cap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cap)
O=R/'runs/paper-completion-20261020/gu-repair-r2-20261022';m=cap.read(O/'manifest.json')
sys.path.insert(0,m['core'])
assert cap.source_identity(m['source'],m['core'])==m['source_identity']
e=cap.load_engine(m['source'],m['core'])
spec=importlib.util.spec_from_file_location('r2_interventions',R/'paper-completion-20261020/gu-repair-r2-20261022/interventions.py');r2=importlib.util.module_from_spec(spec);spec.loader.exec_module(r2)
from token_accounting import request_tokens
requests={};checks=[]
with tempfile.TemporaryDirectory(prefix='advisor-native-zero-') as tmp:
 for mode in ['advisor','deliberation']:
  a=r2.agent_class(e.TwentyAgent,'g1_u1')('memrsi',Path(tmp)/mode,O/'frozen-policy.json',m['budget'])
  a.ops=Advisor(a.provider,a.workspace,a.provider.action_contract,mode)
  (a.workspace/'memory/MEMORY.md').write_text('PUBLIC_NATIVE_MEMORY')
  assert 'PUBLIC_NATIVE_MEMORY' in a.loop.context.build_system_prompt()
  async def stub(**kw):
   requests[mode]=kw
   return NS(finish_reason='tool_calls',tool_calls=[NS(name='report_advice',arguments={'recommendation':'','basis_ids':[],'uncertainty':'No action assumed'})])
  a.provider.chat=stub
  out=asyncio.run(a.ops.guide([{'role':'assistant','content':'PUBLIC_SHORT','tool_calls':[{'id':'public_call'}]}],'PUBLIC_REQUEST'))
  assert a.provider.calls==0 and 'may reject' in out
  assert (a.workspace/'memory/MEMORY.md').read_text()=='PUBLIC_NATIVE_MEMORY'
  assert not (a.workspace/'TASK.md').exists()
  n=request_tokens(requests[mode]['messages'],requests[mode]['tools']);assert n<=a.provider.budget['active_input_tokens']
  checks.append({'mode':mode,'input_tokens':n,'limit':a.provider.budget['active_input_tokens'],'native_MEMORY_visible':True,'provider_calls':a.provider.calls})
assert requests['advisor']['messages'][1]==requests['deliberation']['messages'][1]
assert requests['advisor']['tools']==requests['deliberation']['tools']
assert requests['advisor']['model']==requests['deliberation']['model']
print(json.dumps({'native_checks':checks,'equal_public_input_and_output_schema':True,'real_model_calls':0,'physical_calls':0,'limitation':'Same extra-call opportunity, not equal realized token usage; not a full native self-reflection implementation. Fixture budgets only, not all live inputs.'}))
