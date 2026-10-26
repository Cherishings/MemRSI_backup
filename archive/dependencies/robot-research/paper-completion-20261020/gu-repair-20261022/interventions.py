"""G/U factorial; public runtime data only. No scoring, answers or extra memory."""
import copy,hashlib,json
ARMS=('g0_u0','g1_u0','g0_u1','g1_u1')
G=('Select up to five evidence fragment IDs. The actor already reads MEMORY.md and the current conversation. '
'Use the current request and recent context to distinguish the active request instance from suspended, completed, or cancelled work. '
'Highlight original evidence of relevant changes, unresolved dependencies, or conflicting records that adds something beyond the visible current request. '
'Do not repeat an old continuation as if it overrides a newer request. Keep enough identity and provenance to distinguish similar requests. '
'When supplied records add nothing useful, select no fragments. Return existing IDs only; the program copies exact source text. '
'Do not generate actions, invent facts, or treat an intention as completion. Current user instructions and actual receipts govern; stored claims can be wrong.')
U=('Maintain compact records of distinct request instances, each with its originating public event, authorized outcome, status, and supporting evidence. '
'Keep current work distinct from suspended work and past completed instances. Preserve the scope and order of pending requirements. '
'When a public instruction cancels or revises a requirement, preserve the original reference and the change together, mark the affected requirement as superseded or cancelled, and preserve unaffected requirements. '
'Resolve a relative reference only when the supplied original request and history establish its referent; retain that provenance. Otherwise preserve the exact reference and uncertainty instead of guessing or discarding the change. '
'Receipts update only the matching request instance. A completed interruption does not mean the suspended request is complete, and a stored continuation does not authorize skipping a new request. '
'Prioritize unresolved current requirements, authoritative changes, and verified progress over repetitive historical receipts. Keep history concise within the shared storage budget. '
'Only public requests and actual feedback establish work or completion. Do not manufacture a task, action plan, success claim, or missing fact.')
def policy_for(parent,arm):
 if arm not in ARMS:raise ValueError('unregistered_arm')
 p=copy.deepcopy(parent);p['guidance']=json.dumps({'kind':'procedure_guidance_v2','procedure':G},ensure_ascii=False) if arm.startswith('g1') else ''
 p['update']=json.dumps({'kind':'procedure_update_v2','procedure':U},ensure_ascii=False) if arm.endswith('u1') else ''
 return p
def digest(p):return hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()
def agent_class(base,arm):
 if arm not in ARMS:raise ValueError('unregistered_arm')
 class Repaired(base):
  def __init__(self,*args,**kwargs):
   super().__init__(*args,**kwargs)
   self.policy=policy_for(self.policy,arm);self.policy_hash=digest(self.policy);self.provider.memory_policy=self.policy
   self.requested_boundaries=0;self.actual_boundaries=0
   if self.ops is None:raise RuntimeError('expected_memory_ops_constructor')
   if arm.startswith('g0'):self.ops=None
   else:
    self.ops.policy=self.policy;original=self.ops.guide
    async def guide(short,current):
     self.provider._append('gu-exposure.jsonl',{'arm':arm,'native_short_messages':len(short),'guidance_short_messages':len(short),'native_short_sha256':hashlib.sha256(json.dumps(short,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'current_sha256':hashlib.sha256(current.encode()).hexdigest(),'requested_boundaries':self.requested_boundaries,'actual_boundaries':self.actual_boundaries})
     return await original(short,current)
    self.ops.guide=guide
   self._write('applied-memory-policy.json',self.policy)
   self._write('gu-contract.json',{'arm':arm,'effective_policy_sha256':self.policy_hash,'guidance_enabled':self.ops is not None,'update_enabled':bool(self.provider.memory_policy['update']),'native_archive_preserved':True,'actor_full_memory_access':True,'native_S_preserved':True,'explicit_boundary_interval':2,'native_token_archive_unchanged':True,'manual_design_not_RSI':True,'score_unchanged':True})
  async def rollover(self):
   self.requested_boundaries+=1;execute=self.requested_boundaries%2==0
   self.provider._append('gu-boundaries.jsonl',{'arm':arm,'requested_boundary':self.requested_boundaries,'execute_native_new':execute})
   if execute:
    await super().rollover();self.actual_boundaries+=1
 return Repaired
