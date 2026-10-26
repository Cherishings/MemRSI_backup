"""Independent, hand-designed evidence-focus comparison; no task answers."""
import copy,hashlib,json
ARMS=('cadence2_control','cadence2_delta_guidance')
PROCEDURE=('Select up to five evidence fragment IDs. The actor already reads MEMORY.md and the current conversation; your excerpts should add useful focus, not another summary. '
'Compare the current request and short context with the supplied records. Highlight evidence that could change the current decision and is easy to overlook: an authoritative change, unresolved dependency, or conflicting status tied to the same request instance. '
'Prefer source evidence with enough identity and provenance to avoid mixing similar requests. Do not amplify stale claims or duplicate a self-contained current instruction. '
'If the visible context already provides what is needed and no additional record changes its interpretation, select nothing. '
'Return only IDs of existing fragments; the program copies them verbatim. Never invent facts, resolve uncertainty as completion, prescribe actions, or translate tasks into tools. Original requests and actual feedback govern; remembered claims may be wrong.')
def candidate_policy(policy):
    result=copy.deepcopy(policy);spec=json.loads(result['guidance'])
    if spec['kind']!='procedure_guidance_v2':raise ValueError('unexpected_guidance_kind')
    spec['procedure']=PROCEDURE;result['guidance']=json.dumps(spec,ensure_ascii=False)
    return result

def agent_class(base,arm):
    if arm not in ARMS:raise ValueError('unregistered_arm')
    class Diagnostic(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.requested_boundaries=0;self.actual_boundaries=0
            if self.ops is None:raise RuntimeError('guidance_required')
            if arm=='cadence2_delta_guidance':
                self.policy=candidate_policy(self.ops.policy)
                self.policy_hash=hashlib.sha256(json.dumps(self.policy,sort_keys=True).encode()).hexdigest()
                self.provider.memory_policy=self.policy
                self.ops.policy=self.policy
                self._write('applied-memory-policy.json',self.policy)
            original=self.ops.guide
            async def guide(short,current):
                self.provider._append('diagnostic-exposure.jsonl',{'arm':arm,'native_short_messages':len(short),'guidance_short_messages':len(short),'native_short_sha256':hashlib.sha256(json.dumps(short,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'actor_history_untouched':True,'requested_boundaries':self.requested_boundaries,'actual_explicit_boundaries':self.actual_boundaries})
                return await original(short,current)
            self.ops.guide=guide
            self._write('diagnostic-intervention.json',{'arm':arm,'selection_cap':5,'explicit_boundary_interval':2,'automatic_native_token_consolidation_unchanged':True,'actor_full_MEMORY_access_unchanged':True,'update_policy_unchanged':True,'effective_guidance_policy':self.ops.policy,'manual_design_not_RSI':True})
        async def rollover(self):
            self.requested_boundaries+=1;execute=self.requested_boundaries%2==0
            self.provider._append('diagnostic-boundaries.jsonl',{'requested_index':self.requested_boundaries,'execute_native_new':execute,'reason':'registered_interval','arm':arm})
            if execute:
                await super().rollover();self.actual_boundaries+=1
    return Diagnostic
