"""Training-language atomic task surface, shared by both arms."""
import json
from visual_actor import VisualAgent
from action_commit_boundary import install_commit_boundary
from adapted_action_contract import AtomicCoverAction,RMB_CONTRACT,install_action
class RMBVisualAgent(VisualAgent):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);install_action(self,AtomicCoverAction(),RMB_CONTRACT);install_commit_boundary(self)
    async def choose(self,request_text,cameras,proprio):
        state=json.dumps(self.action.committed_instruction,ensure_ascii=False)
        return await super().choose(request_text+'\nCurrent committed atomic controller instruction: '+state+'. Choose one primitive/target or continue/finish as specified by report_action.',cameras,proprio)
