"""Pristine PAOS core plus an explicitly shared physical action adapter.

Native: unchanged native memory, archive prompts, session and context builder.
MemRSI: L is the single native MEMORY.md authority; S is the native session.
G(L,S,current) produces ephemeral guidance, and U(S,L) changes the native
archive procedure. Neither operator reads evaluator facts or prevents finish.
"""
import hashlib
import copy
import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import PhyAgentOS
from loguru import logger
from PhyAgentOS.agent.loop import AgentLoop
from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.bus.queue import MessageBus

from memory_ops import MemoryOps
from memory_policy import archive_request, digest, load
from model_provider import MODEL, Provider

COMMON_TOOLS = (
    'Use report_action to submit one action, then wait for execution feedback. '
    'The skill argument accepts serve_table_one (run the configured service procedure at station one), '
    'serve_table_two (run the configured service procedure at station two), '
    'execute_order (run the currently assigned kitchen work order), or finish (end this run). '
    'The procedure identifiers are tool argument values, not separate tools or files. '
    'Selecting a station action routes execution to that station automatically; manual navigation is not required. '
    'These actions use a real simulated gripper. Results are supplied after execution. '
    'Each station skill runs its ENTIRE native task, not one object placement. '
    'serve_table_one places the white mug on its plate AND the pudding to the right; '
    'serve_table_two places both mugs on their respective plates. '
    'Only an explicitly announced partial-execution request pauses after one placement. '
    'Execution receipts distinguish segment_success from native_task_complete; '
    'the latter reports completion of the whole native task, not a plan or an intention. '
    'Do not access other trials or write scripts. ')


class ProcedureProvider(Provider):
    def __init__(self, output, policy):
        super().__init__(output)
        self.memory_policy = policy
        self.action_contract = COMMON_TOOLS

    async def chat(self, **kwargs):
        request = archive_request(kwargs, self.memory_policy)
        if request is not kwargs:
            # U needs the same public capability definitions as G and the actor.
            # The native baseline still uses its original archive prompt.
            request = copy.deepcopy(request)
            request['messages'][0]['content'] += (
                '\nPublic execution API (capabilities, not requested work):\n' + self.action_contract +
                '\nDo not turn visible objects into requested tasks. Preserve what the user '
                'requested and what execution receipts actually confirm; a tool capability '
                'by itself is not evidence of an outstanding request.')
            self._append('procedure-usage.jsonl', {
                'phase': 'native_archive_update',
                'policy_sha256': digest(self.memory_policy),
            })
        return await super().chat(**request)


class Action(Tool):
    name = 'report_action'
    description = 'Commit ONE next physical skill or finish. Only the first call in a turn is accepted. End your turn after this call and wait for execution feedback.'
    parameters = {'type': 'object', 'properties': {
        'skill': {'type': 'string', 'enum': ['serve_table_one', 'serve_table_two', 'execute_order', 'finish']},
        'reason': {'type': 'string'}}, 'required': ['skill', 'reason'], 'additionalProperties': False}

    def __init__(self):
        self.records, self.rejected = [], []

    async def execute(self, skill, reason):
        if self.records:
            self.rejected.append({'skill': skill, 'reason': reason})
            return 'Rejected: one skill already committed. No additional action is queued. End your turn.'
        self.records.append({'skill': skill, 'reason': reason})
        return 'Decision committed, not executed yet. End your turn and await physical feedback.'


class Agent:
    provider_type = ProcedureProvider
    def __init__(self, arm, output, memory_policy=None):
        logger.remove()
        if arm not in ('native', 'memrsi'):
            raise ValueError('unknown_arm')
        if arm == 'native' and memory_policy is not None:
            raise ValueError('baseline_has_no_added_policy')
        if arm == 'memrsi' and memory_policy is None:
            raise ValueError('rsi_requires_explicit_versioned_policy')
        self.arm, self.output = arm, Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.policy = load(memory_policy)
        self.policy_hash = digest(self.policy)
        self.workspace = self.output.parents[1] / 'workspaces' / uuid.uuid4().hex
        self.workspace.mkdir(parents=True)
        self.session_key = 'cli:' + uuid.uuid4().hex
        self.event_id, self.rollovers = 0, []
        self.memory = SimpleNamespace(revision=0)
        self._write('workspace-location.json', {
            'workspace': str(self.workspace), 'session_key': self.session_key,
        })
        self._write('applied-memory-policy.json', self.policy)
        self._write('memory-backend.json', {
            'backend': 'paos_native_single_long_authority',
            'long_memory': 'memory/MEMORY.md', 'history': 'memory/HISTORY.md',
            'short_memory': 'native session messages',
            'guidance': 'ephemeral model-generated TASK.md' if arm == 'memrsi' else None,
            'additional_task_ledger': False, 'handwritten_finish_guard': False,
            'policy_learning_during_evaluation': False,
            'imported_paos_package': str(Path(PhyAgentOS.__file__).resolve()),
            'max_iterations': 40, 'context_window_tokens': 65536,
        })
        template = Path(PhyAgentOS.__file__).resolve().parent / 'templates'
        for name in ('AGENTS.md', 'SOUL.md'):
            shutil.copyfile(template / name, self.workspace / name)
        (self.workspace / 'TOOLS.md').write_text(COMMON_TOOLS)
        self.provider = self.provider_type(self.output, self.policy)
        self.loop = AgentLoop(bus=MessageBus(), provider=self.provider,
            workspace=self.workspace, model=MODEL, max_iterations=40,
            context_window_tokens=65536, restrict_to_workspace=True)
        for name in list(self.loop.tools.tool_names):
            if name not in ('read_file', 'write_file', 'edit_file', 'list_dir'):
                self.loop.tools.unregister(name)
        self.action = Action()
        self.loop.tools.register(self.action)
        self.ops = MemoryOps(self.provider, self.workspace, self.output, self.policy, COMMON_TOOLS) if arm == 'memrsi' else None

    def _write(self, name, value):
        (self.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))

    def _record_event(self, text, decision, *, replay=False):
        self.event_id += 1
        with (self.output / 'received-events.jsonl').open('a') as stream:
            stream.write(json.dumps({
                'id': self.event_id, 'text': text, 'decision_requested': decision,
                'replay': replay,
            }, ensure_ascii=False) + '\n')
        return 'Event %d: %s' % (self.event_id, text)

    def _clear_guidance(self):
        # Only MemRSI owns this transient file; never delete baseline-authored data.
        if self.ops is not None:
            (self.workspace / 'TASK.md').unlink(missing_ok=True)

    async def observe_only(self, text, facts=None):
        # Compatibility argument facts is intentionally unused.
        message = self._record_event(text, False)
        session = self.loop.sessions.get_or_create(self.session_key)
        session.add_message('user', message)
        self.loop.sessions.save(session)

    async def replay_observe(self, text, decision_record=None):
        """Feed recorded public history without executing or supplying a score."""
        message = self._record_event(text, decision_record is not None, replay=True)
        session = self.loop.sessions.get_or_create(self.session_key)
        session.add_message('user', message)
        if decision_record is not None:
            # Explicit allowlist: no expected/correct/reward/outcome metadata.
            action = {key: decision_record[key] for key in ('skill', 'reason') if key in decision_record}
            session.add_message('assistant', 'Recorded previous action decision: ' +
                                json.dumps(action, ensure_ascii=False))
        self.loop.sessions.save(session)

    async def turn(self, text, facts=None, decision=False):
        message = self._record_event(text, decision)
        memory_file = self.workspace / 'memory/MEMORY.md'
        memory_before = memory_file.read_text() if memory_file.exists() else ''
        self._clear_guidance()
        if self.ops is not None and decision:
            session = self.loop.sessions.get_or_create(self.session_key)
            guidance = await self.ops.guide(session.get_history(max_messages=0), message)
            if not isinstance(guidance, str):
                raise RuntimeError('invalid_guidance')
            (self.workspace / 'TASK.md').write_text(guidance)
        self.action.records, self.action.rejected = [], []
        try:
            response = await self.loop.process_direct(message, session_key=self.session_key)
            if decision and not self.action.records:
                # One answer-free protocol repair, shared by all arms/replay.
                # Nothing was dispatched. Never translate prose into a chosen action.
                self.provider.format_repairs += 1
                self.provider._append('action-format-repairs.jsonl', {
                    'event_id': self.event_id, 'initial_response': response,
                    'reason': 'no_action_tool_call', 'max_repairs': 1})
                response = await self.loop.process_direct(
                    'Submit one report_action for the pending decision. No new task or correct answer is supplied.',
                    session_key=self.session_key)
        finally:
            # Guidance is recomputed from fresh L/S at the next decision.
            self._clear_guidance()
            memory_after = memory_file.read_text() if memory_file.exists() else ''
            if memory_after != memory_before:
                self.provider._append('actor-memory-writes.jsonl', {
                    'event_id': self.event_id, 'before': memory_before, 'after': memory_after,
                    'scope': 'actor file-tool write, not an archival Update invocation'})
        if not decision:
            return response
        if len(self.action.records) != 1:
            raise RuntimeError('action_protocol_failure')
        return self.action.records[0]

    async def rollover(self):
        self._clear_guidance()
        index = len(self.rollovers) + 1
        snapshot = self.output / ('rollover-%d' % index)
        snapshot.mkdir()
        session = self.loop.sessions.get_or_create(self.session_key)
        before = len(session.messages)
        (snapshot / 'messages-before.json').write_text(json.dumps(session.messages, ensure_ascii=False, indent=2))
        memory = self.workspace / 'memory/MEMORY.md'
        old = memory.read_bytes() if memory.exists() else b''
        (snapshot / 'memory-before.md').write_bytes(old)
        response = await self.loop.process_direct('/new', session_key=self.session_key)
        after = len(self.loop.sessions.get_or_create(self.session_key).messages)
        ok = response.strip() == 'New session started.' and before > 0 and after == 0
        new = memory.read_bytes() if memory.exists() else b''
        (snapshot / 'memory-after.md').write_bytes(new)
        if ok and old != new:
            self.memory.revision += 1
        for path in self.workspace.rglob('*.md'):
            dest = snapshot / 'persistent-after' / path.relative_to(self.workspace)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        record = {
            'index': index, 'command': '/new', 'response': response,
            'before_messages': before, 'after_messages': after, 'success': ok,
            'last_received_event': self.event_id,
            'memory_before_sha256': hashlib.sha256(old).hexdigest(),
            'memory_after_sha256': hashlib.sha256(new).hexdigest(),
            'policy_sha256': self.policy_hash, 'model_calls': self.provider.calls,
        }
        self.rollovers.append(record)
        (snapshot / 'audit.json').write_text(json.dumps(record, indent=2))
        if not ok:
            raise RuntimeError('native_session_archival_failed')

    async def close(self):
        self._clear_guidance()
        await self.provider._client.close()
