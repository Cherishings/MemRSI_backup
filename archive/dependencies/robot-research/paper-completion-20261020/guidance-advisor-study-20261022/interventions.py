"""Four finite development controls; same U, actor and common receipt interface."""
import json
from advisor import Advisor, MODES
from base_interventions import agent_class as prior_class, policy_for as prior_policy, digest
ARMS=('off_u1','evidence_u1','advisor_u1','deliberation_u1')
def policy_for(parent,arm):
 if arm not in ARMS:raise ValueError('unregistered_arm')
 p=prior_policy(parent,'g1_u1' if arm=='evidence_u1' else 'g0_u1')
 if arm in ('advisor_u1','deliberation_u1'):
  p['guidance']=json.dumps({'kind':'procedure_guidance_v2','procedure':MODES[arm.split('_')[0]]},ensure_ascii=False)
 return p

def agent_class(base,arm):
 if arm not in ARMS:raise ValueError('unregistered_arm')
 class Study(prior_class(base,'g1_u1' if arm=='evidence_u1' else 'g0_u1')):
  def __init__(self,*args,**kwargs):
   super().__init__(*args,**kwargs)
   self.policy=policy_for(self.policy,arm);self.policy_hash=digest(self.policy);self.provider.memory_policy=self.policy
   if arm in ('advisor_u1','deliberation_u1'):self.ops=Advisor(self.provider,self.workspace,self.provider.action_contract,arm.split('_')[0])
   elif self.ops is not None:self.ops.policy=self.policy
   self._write('applied-memory-policy.json',self.policy)
   self._write('advisor-contract.json',{'arm':arm,'guidance_enabled':arm!='off_u1','update_enabled':True,'mode':arm.split('_')[0],'actor_full_MEMORY':True,'same_U':True,'manual_not_RSI':True})
 return Study
