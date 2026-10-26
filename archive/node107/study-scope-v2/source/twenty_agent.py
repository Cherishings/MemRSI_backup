"""Twenty-session adapter; original PAOS package remains byte-for-byte frozen."""
import copy
import json
from pathlib import Path
from agent_adapter import Agent, ProcedureProvider
from memory_budget import BoundedStore, LimitedFileTool
from token_accounting import request_tokens, memory_tokens
from twenty_protocol import TOOLS
from action_catalog import action_parameters

class BudgetProvider(ProcedureProvider):
    async def _chat_attempts_locked(self, **kwargs):
        n = request_tokens(kwargs['messages'], kwargs.get('tools'))
        limit = self.budget['active_input_tokens']
        self._append('context-capacity.jsonl', {'input_tokens': n, 'limit': limit,
            'accounting': 'o200k_base_serialized_messages_and_tools',
            'status': 'accepted' if n <= limit else 'rejected'})
        if n > limit:
            self.budget_error = 'active_context_budget_exceeded'
            raise RuntimeError(self.budget_error)
        return await super()._chat_attempts_locked(**kwargs)

class TwentyAgent(Agent):
    provider_type = BudgetProvider
    def __init__(self, arm, output, memory_policy, budget):
        super().__init__(arm, output, memory_policy)
        config = json.loads(Path(budget).read_text()) if not isinstance(budget, dict) else budget
        if config['persistent_tokens'] < 1 or config['active_input_tokens'] < 1:
            raise ValueError('invalid_budget')
        self.provider.budget, self.provider.budget_error = config, None
        self.store = BoundedStore(self.workspace, config['persistent_tokens'], self.provider._append)
        self.loop.context.memory = self.store
        self.loop.memory_consolidator.store = self.store
        self.loop.memory_consolidator.context_window_tokens = config['active_input_tokens']
        self.loop.context_window_tokens = config['active_input_tokens']
        # Use protocol accounting in the original consolidation trigger. The
        # original safe-turn-boundary selection and archive rules stay intact.
        def estimate(session):
            messages = self.loop.context.build_messages(history=session.get_history(max_messages=0),
                current_message='[token-probe]', channel='cli', chat_id=self.session_key.split(':', 1)[1])
            return request_tokens(messages, self.loop.tools.get_definitions()), 'o200k_base_protocol'
        self.loop.memory_consolidator.estimate_session_prompt_tokens = estimate
        (self.workspace / 'TOOLS.md').write_text(TOOLS +
            f' Shared resource limits: MEMORY.md and HISTORY.md together may contain at most '
            f'{config["persistent_tokens"]} o200k_base tokens; only these two files are writable. '
            'Other trial/session logs are not available to the actor.')
        self.action.parameters = action_parameters()
        self.provider.action_contract = TOOLS
        for name in ('read_file', 'write_file', 'edit_file', 'list_dir'):
            inner = self.loop.tools.get(name)
            self.loop.tools.register(LimitedFileTool(inner, self.workspace, self.store))
        if self.ops:
            self.ops.action_contract = TOOLS
        self._write('resource-budget.json', dict(config,
            native_extra_memory_policy=False, persistent_paths=['memory/MEMORY.md', 'memory/HISTORY.md'],
            common_overflow_adapter='model_repacking_without_task_specific_rules',
            session_log_actor_access=False, entry_limit=None))
        backend = json.loads((self.output / 'memory-backend.json').read_text())
        backend.update(context_window_tokens=config['active_input_tokens'],
                       persistent_tokens=config['persistent_tokens'],
                       backend='paos_native_memory_with_shared_capacity_adapter')
        self._write('memory-backend.json', backend)

    async def turn(self, *args, **kwargs):
        # Consolidate only by the original PAOS safe boundary mechanism; never
        # feed archived session messages into MemRSI's short-memory guide.
        session = self.loop.sessions.get_or_create(self.session_key)
        await self.loop.memory_consolidator.maybe_consolidate_by_tokens(session)
        try:
            return await super().turn(*args, **kwargs)
        except Exception:
            if self.provider.budget_error:
                raise RuntimeError(self.provider.budget_error) from None
            raise

    async def rollover(self):
        try:
            await super().rollover()
        except Exception:
            code = self.provider.budget_error or self.store.last_failure
            if code:
                raise RuntimeError(code) from None
            raise
        n = memory_tokens(self.store.read_long_term(), self.store.history_file.read_text())
        if n > self.store.limit:
            raise RuntimeError('persistent_memory_budget_exhausted')
