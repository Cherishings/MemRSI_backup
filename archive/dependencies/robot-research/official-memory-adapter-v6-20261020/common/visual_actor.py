"""Common camera/subgoal interface; no expert state, answer, or stop veto.

Loads the frozen v2.2 agent package. Only the public action surface and visual
input/resource adapter change; PAOS archive/session and MemRSI G/U stay intact.
"""
import json
import os
from pathlib import Path
import sys

from observation_evidence import OBSERVATION_SCHEMA, validate_observation, render_observation

from visual_accounting import (accounting_messages, public_proprio,
    image_evidence, MAX_CAMERAS, MAX_IMAGE_EDGE, IMAGE_UNITS)

CORE = Path(os.environ.get('MEMRSI_FROZEN_CORE',
    '/data/stormlab/xi/paos/worktrees/memrsi-bounded-v2_2'))
sys.path.insert(0, str(CORE))
from twenty_agent import TwentyAgent, BudgetProvider
from agent_adapter import ProcedureProvider
from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.bus.events import InboundMessage
from token_accounting import request_tokens
from visual_budget import (GUIDANCE_RESERVE_UNITS, NATIVE_CAPACITY_ERROR,
    contains_user_message, install_native_counter, request_resource_units)

CONTRACT = (
    'Use report_action to submit ONE next low-level instruction, or finish. '
    'skill=execute sends the instruction string to the shared frozen robot '
    'controller for a bounded action chunk. It is not a promise of completion. '
    'skill=finish ends this episode. Use an empty instruction when finishing. '
    'The next observation is the result of actual execution. Cameras and robot '
    'joint/end-effector readings are supplied; no expert plan is available. '
    'Include observation with visible_facts, progress_uncertainty and reference_to_preserve. '
    'Describe what you can currently observe before this action, separately from intentions. '
    'These are your uncertain visual claims, not verified completion or hidden state. '
    'Use empty strings for unavailable evidence. No new observation is inferred by the interface. '
    'Wait for execution feedback after committing one action. '
    'Do not read other trials, evaluator files, or write scripts.'
)


class VisualProvider(BudgetProvider):
    async def chat(self, **kwargs):
        ledger = os.environ.get("MEMRSI_LEARNING_LEDGER")
        from model_provider import CALL_LIMIT
        if ledger and self.calls < CALL_LIMIT:
            from learning_budget import charge
            charge(ledger, os.environ.get("MEMRSI_PHASE", "development"), os.environ.get("MEMRSI_CASE_ID", "unknown"))
        return await super().chat(**kwargs)

    async def _chat_attempts_locked(self, **kwargs):
        normalized, image_units, count = accounting_messages(kwargs['messages'])
        text_units = request_tokens(normalized, kwargs.get('tools'))
        total = text_units + image_units
        limit = self.budget['active_input_tokens']
        self._append('context-capacity.jsonl', dict(
            input_tokens=total, text_units=text_units, image_units=image_units,
            images=count, limit=limit,
            accounting='visual_v1_o200k_text_plus_1024_units_per_image_not_vendor_billing',
            status='accepted' if total <= limit else 'rejected'))
        if total > limit:
            self.budget_error = 'active_context_budget_exceeded'
            raise RuntimeError(self.budget_error)
        # Bypass only the text-only base64 counter, not the shared transport.
        return await ProcedureProvider._chat_attempts_locked(self, **kwargs)


class InstructionAction(Tool):
    name = 'report_action'
    description = 'Commit one robot instruction or finish; execution happens later.'
    parameters = {'type': 'object', 'properties': {
        'skill': {'type': 'string', 'enum': ['execute', 'finish']},
        'instruction': {'type': 'string', 'maxLength': 512},
        'reason': {'type': 'string', 'maxLength': 512},
        'observation': OBSERVATION_SCHEMA},
        'required': ['skill', 'instruction', 'reason', 'observation'], 'additionalProperties': False}

    def __init__(self):
        self.records, self.rejected = [], []
        self.event_id = 0

    async def execute(self, skill, instruction, reason, observation):
        evidence = render_observation(self.event_id, validate_observation(observation))
        if self.records:
            self.rejected.append(dict(skill=skill, instruction=instruction, reason=reason))
            return 'Rejected: an action was already committed. Wait for execution feedback.'
        if skill not in ('execute', 'finish') or not isinstance(instruction, str):
            return 'Invalid public tool arguments. No action was dispatched.'
        if (skill == 'execute' and not instruction.strip()) or (skill == 'finish' and instruction):
            return 'Execute needs an instruction; finish needs an empty instruction. No action was dispatched.'
        self.records.append(dict(skill=skill, instruction=instruction, reason=reason, observation=observation))
        return evidence + '\nDecision committed, not yet executed. Wait for physical feedback.'


class VisualAgent(TwentyAgent):
    provider_type = VisualProvider

    def __init__(self, arm, output, memory_policy, budget):
        install_native_counter()
        super().__init__(arm, output, memory_policy, budget)
        self.action = InstructionAction()
        self.loop.tools.register(self.action)
        self.provider.action_contract = CONTRACT
        if self.ops:
            self.ops.action_contract = CONTRACT
        (self.workspace / 'TOOLS.md').write_text(CONTRACT +
            ' Only memory/MEMORY.md and memory/HISTORY.md are writable. '
            f'Shared persistent memory limit: {self.store.limit} tokens.')
        self._native_process_direct = self.loop.process_direct
        self._pending_media = []
        self._visual_pending = None
        self._visual_phase = None
        self._plain_archive_estimator = self.loop.memory_consolidator.estimate_session_prompt_tokens
        self.loop.memory_consolidator.estimate_session_prompt_tokens = self._estimate_visual_session
        resource = json.loads((self.output / 'resource-budget.json').read_text())
        resource.update(visual_adapter_version='v3-observation-evidence',
            pre_guidance_archive_reserve_units=GUIDANCE_RESERVE_UNITS,
            archive_reserve_shared_by_both_arms=True,
            archive_reserve_is_extra_input_capacity=False,
            provider_and_native_tool_counter='o200k_text_plus_1024_per_image')
        self._write('resource-budget.json', resource)
        self.loop.process_direct = self._process_camera_message
        self._write('visual-adapter.json', dict(
            version='official-memory-visual-v3', common_for_both_arms=True,
            memory_rule_changed=False, action_contract=CONTRACT,
            active_input_units=budget['active_input_tokens'],
            persistent_tokens=budget['persistent_tokens'], image_units=IMAGE_UNITS,
            max_cameras=MAX_CAMERAS, max_image_edge=MAX_IMAGE_EDGE,
            image_history='native PAOS image placeholders unchanged; bounded actor observation in common action tool result',
            observation_limit_chars=768, observation_is_unverified=True,
            observation_extra_model_calls=0,
            oracle_input=False, vendor_token_claim=False,
            archive_estimator='actual pending Event text, proprio, media, system, and tool definitions',
            pre_guidance_archive_reserve_units=GUIDANCE_RESERVE_UNITS,
            reserve_shared_by_both_arms=True,
            reserve_is_archive_trigger_margin_not_extra_input_capacity=True,
            native_tool_compaction_counter='same as provider visual resource counter',
            native_archive_algorithm_changed=False))

    def _estimate_visual_session(self, session):
        pending = self._visual_pending
        history = session.get_history(max_messages=0)
        # Native post-turn consolidation sees the just-saved turn. Do not append
        # the same current message/images again after PAOS has saved it as [image].
        if pending is None or contains_user_message(history, pending['text']):
            return self._plain_archive_estimator(session)
        messages = self.loop.context.build_messages(history=history,
            current_message=pending['text'], media=pending['media'],
            channel='cli', chat_id='direct')
        measured = request_resource_units(messages, self.loop.tools.get_definitions())
        reserve = GUIDANCE_RESERVE_UNITS if self._visual_phase == 'before_guidance' else 0
        # The same pre-G allowance is used for native and MemRSI. Once G exists,
        # build_messages includes its actual TASK.md content, with no hidden slack.
        self.provider._append('visual-archive-estimates.jsonl', dict(
            event=self.event_id + (self._visual_phase == 'before_guidance'),
            phase=self._visual_phase, actual_request_units=measured,
            shared_guidance_reserve_units=reserve, trigger_units=measured + reserve))
        return measured + reserve, 'visual_v2_actual_pending_request_with_shared_pre_G_reserve'

    async def turn(self, *args, **kwargs):
        try:
            return await super().turn(*args, **kwargs)
        except ValueError as error:
            if str(error) == NATIVE_CAPACITY_ERROR:
                raise RuntimeError('active_context_budget_exceeded') from None
            raise

    async def _process_camera_message(self, content, session_key='cli:direct',
                                     channel='cli', chat_id='direct', on_progress=None):
        media, self._pending_media = self._pending_media, []
        if not media:
            return await self._native_process_direct(content, session_key=session_key,
                channel=channel, chat_id=chat_id, on_progress=on_progress)
        if self._visual_pending is None or content != self._visual_pending['text']:
            raise RuntimeError('visual_pending_event_mismatch')
        self._visual_phase = 'actor'
        # Read-only audit of what THIS actor actually received. Never fed back
        # into evaluation; the development exporter applies a split allowlist.
        guide = self.workspace / 'TASK.md'
        self._current_guidance_audit = guide.read_text() if guide.exists() else ''
        await self.loop._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id='user', chat_id=chat_id,
                             content=content, media=media)
        response = await self.loop._process_message(msg, session_key=session_key,
                                                   on_progress=on_progress)
        return response.content if response else ''

    async def choose(self, request_text, cameras, proprio):
        import numpy as np
        from PIL import Image
        if not 1 <= len(cameras) <= MAX_CAMERAS:
            raise ValueError('camera_budget_exceeded')
        readings = public_proprio(proprio)
        folder = self.output / 'cameras' / f'{self.event_id + 1:05d}'
        folder.mkdir(parents=True, exist_ok=False)
        paths = []
        for i, rgb in enumerate(cameras):
            a = np.asarray(rgb)
            if a.dtype != np.uint8 or a.ndim != 3 or a.shape[2] != 3:
                raise ValueError('camera_requires_uint8_RGB')
            im = Image.fromarray(a)
            im.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            path = folder / f'camera-{i}.png'
            im.save(path); paths.append(path)
        self.provider._append('visual-inputs.jsonl', dict(
            event=self.event_id + 1, cameras=image_evidence(paths),
            public_proprio=readings, no_evaluator_fields=True))
        self.action.event_id = self.event_id + 1
        self._pending_media = [str(p) for p in paths]
        message = request_text + '\nCurrent robot readings: ' + json.dumps(readings, sort_keys=True)
        self._visual_pending = dict(text=f'Event {self.event_id + 1}: {message}',
                                    media=list(self._pending_media))
        self._visual_phase = 'before_guidance'
        def memory_snapshot():
            return '\n'.join(p.name + ':\n' + p.read_text() for p in
                [self.workspace / 'memory/MEMORY.md', self.workspace / 'memory/HISTORY.md']
                if p.exists())
        memory_before = memory_snapshot()
        self._current_guidance_audit = ''
        # Public input evidence survives an invalid first action or a capacity
        # failure. This is an audit only: it does not enter memory or scoring.
        self.provider._append('public-decision-inputs.jsonl', dict(
            event_id=self.event_id + 1, public_request=request_text,
            memory_before=memory_before,
            snapshot_scope='before_decision_not_archive_attribution'))
        try:
            choice = await self.turn(message, decision=True)
            self.provider._append('public-action-audit.jsonl', dict(
                event_id=self.event_id, public_request=request_text, choice=choice,
                memory_before=memory_before, memory_after=memory_snapshot(),
                guidance_selected=self._current_guidance_audit,
                snapshot_scope='decision_boundary_not_archive_attribution'))
            return choice
        finally:
            self._pending_media = []
            self._visual_pending = None
            self._visual_phase = None

    async def observe(self, receipt_text):
        self.provider._append('public-receipts.jsonl', dict(
            preceding_action_event=self.action.event_id, public_receipt=receipt_text))
        await self.observe_only(receipt_text)
