"""Common public adapter semantics; no evaluator, state oracle or forced stop."""
import copy
from visual_actor import InstructionAction, VisualAgent, CONTRACT

COMPLETION_SCHEMA = {'type':'object','properties':{
    'observed_history':{'type':'string','maxLength':512},
    'unverified_obligations':{'type':'string','maxLength':256}},
    'required':['observed_history','unverified_obligations'],'additionalProperties':False}
COMPLETION_CONTRACT = (
    ' Include completion_evidence with observed_history and unverified_obligations. '
    'Separate actual observed/executed history from plans and intentions. '
    'A current scene that resembles the initial scene does not establish that a temporally ordered task happened. '
    'For finish, state the observed evidence for the requested history as well as the final state; '
    'state unresolved facts honestly. These claims are not verified by the interface. '
    'Finish remains your decision and is not vetoed. Empty evidence is allowed when unavailable.'
)
def validate_completion(value):
    if not isinstance(value,dict) or set(value)!={'observed_history','unverified_obligations'}:
        raise ValueError('completion_evidence_schema')
    for key,limit in [('observed_history',512),('unverified_obligations',256)]:
        if not isinstance(value[key],str) or len(value[key])>limit:raise ValueError('completion_evidence_bound')
    return dict(value)
def install_action(agent,action,contract):
    agent.action=action;agent.loop.tools.register(action)
    agent.provider.action_contract=contract
    if agent.ops:agent.ops.action_contract=contract
    (agent.workspace/'TOOLS.md').write_text(contract+' Only memory/MEMORY.md and memory/HISTORY.md are writable. '+f'Shared persistent memory limit: {agent.store.limit} tokens.')
    agent._write('controller-adaptation.json',dict(version='v6',both_arms_identical=True,extra_model_calls=0,oracle_input=False,finish_veto=False,automatic_task_plan=False,contract=contract))

POSITIONS=('left','middle','right')
def atomic_instruction(primitive,target):
    if target not in POSITIONS or primitive not in ('cover','open'):raise ValueError('invalid_atomic_target')
    if primitive=='cover':return f'Cover the {target} block with the {target} cover.'
    return f'Open the {target} cover to uncover the blocks in the order of red, green, and blue.'

ADAPTER_BASE = CONTRACT.replace('ONE next low-level instruction','ONE next action').replace('sends the instruction string','sends the selected action').replace('Use an empty instruction when finishing.','No instruction string is accepted by this public action tool.')
RMB_CONTRACT = ADAPTER_BASE+COMPLETION_CONTRACT+(
    ' This controller was trained on one cover manipulation at a time. '
    'For execute choose primitive=cover or open and exactly one target=left,middle,right. '
    'The target is your chosen cover position, not a hidden color lookup. '
    'The interface only formats your choice into the published action language; it does not select targets or order. '
    'continuity=start commits your first atomic subgoal; replace explicitly commits a different subgoal. '
    'continue uses primitive=none,target=none to keep the current instruction and execution history. '
    'A subgoal may take multiple chunks. Inspect feedback before replacing it; a predicted boundary is not proof of completion. '
    'For finish choose continuity=none,primitive=none,target=none.'
)
class AtomicCoverAction(InstructionAction):
    description='Commit one chosen atomic cover operation, continue it, or finish; no automatic task order.'
    parameters=copy.deepcopy(InstructionAction.parameters)
    del parameters['properties']['instruction'];parameters['required'].remove('instruction')
    parameters['properties'].update(primitive={'type':'string','enum':['cover','open','none']},target={'type':'string','enum':['left','middle','right','none']},continuity={'type':'string','enum':['start','continue','replace','none']},completion_evidence=COMPLETION_SCHEMA)
    parameters['required']+=['primitive','target','continuity','completion_evidence']
    def __init__(self):
        super().__init__();self.committed_instruction=None
    async def execute(self,skill,reason,observation,primitive,target,continuity,completion_evidence):
        evidence=validate_completion(completion_evidence)
        if self.records:return 'Rejected: an action was already committed. Wait for execution feedback.'
        if skill=='finish':
            if (primitive,target,continuity)!=('none','none','none'):return 'Finish requires none for primitive, target and continuity. No action dispatched.'
            instruction=''
        elif skill=='execute':
            if continuity=='continue':
                if self.committed_instruction is None or (primitive,target)!=('none','none'):return 'Continue requires an existing instruction and none primitive/target. No action dispatched.'
                instruction=self.committed_instruction
            elif continuity in ('start','replace'):
                if (continuity=='start')!=(self.committed_instruction is None):return 'Use start only for the first subgoal, otherwise replace. No action dispatched.'
                try:instruction=atomic_instruction(primitive,target)
                except ValueError:return 'Choose exactly one allowed primitive and position. No action dispatched.'
            else:return 'Execute requires start, continue or replace. No action dispatched.'
        else:return 'Invalid skill. No action dispatched.'
        reply=await super().execute(skill,instruction,reason,observation)
        if self.records:
            self.records[-1].update(continuity=continuity,primitive=primitive,target=target,completion_evidence=evidence)
            if skill=='execute':self.committed_instruction=instruction
        return reply+' Completion evidence is an unverified model report: '+str(evidence)

REMEM_CONTRACT = ADAPTER_BASE+COMPLETION_CONTRACT+(
    ' This PRISM controller uses the original public whole-task language as a fixed episode condition, '
    'matching its training interface. report_action has no instruction argument in this adapter. '
    'execute continues the same task for at most32 real control steps with new camera feedback. '
    'Your role is observation, memory and the continue/finish decision; you cannot issue arbitrary motion subgoals '
    'to this controller. No hidden task state or verified completion is supplied.'
)
class FixedTaskAction(InstructionAction):
    description='Continue the original fixed whole task, or finish, with public observation and completion evidence.'
    parameters=copy.deepcopy(InstructionAction.parameters)
    del parameters['properties']['instruction'];parameters['required'].remove('instruction')
    parameters['properties']['completion_evidence']=COMPLETION_SCHEMA;parameters['required'].append('completion_evidence')
    def __init__(self,goal):
        super().__init__()
        if not isinstance(goal,str) or not goal.strip():raise ValueError('public_task_goal_required')
        self.goal=goal
    async def execute(self,skill,reason,observation,completion_evidence):
        evidence=validate_completion(completion_evidence)
        if self.records:return 'Rejected: an action was already committed. Wait for execution feedback.'
        # Only the original public task is passed; no stage language modifies PRISM.
        reply=await super().execute(skill,self.goal if skill=='execute' else '',reason,observation)
        if self.records:self.records[-1].update(completion_evidence=evidence,controller_condition='fixed_public_task')
        return reply+' Completion evidence is an unverified model report: '+str(evidence)
class FixedTaskVisualAgent(VisualAgent):
    def bind_public_goal(self,goal):
        install_action(self,FixedTaskAction(goal),REMEM_CONTRACT)
