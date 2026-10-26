"""Shared capacity adapter. No task-specific priority, scoring or finish guard.

PAOS performs its original consolidation first. Only an over-capacity write is
packed by the same model under a neutral storage limit. Neither truncation nor
an evaluator decides which facts survive. Failed packing rolls the write back.
"""
import json
from pathlib import Path
from PhyAgentOS.agent.memory import MemoryStore
from PhyAgentOS.agent.tools.base import Tool
from token_accounting import memory_tokens

PACK_TOOL = [{'type': 'function', 'function': {
    'name': 'pack_storage', 'description': 'Replace the contents of two capacity-limited files.',
    'parameters': {'type': 'object', 'properties': {
        'memory': {'type': 'string'}, 'history': {'type': 'string'}},
        'required': ['memory', 'history'], 'additionalProperties': False}}}]

def pair(store):
    return tuple(p.read_text() if p.exists() else '' for p in (store.memory_file, store.history_file))

def write_pair(store, data):
    for path, text in zip((store.memory_file, store.history_file), data):
        path.write_text(text)

class BoundedStore(MemoryStore):
    def __init__(self, workspace, limit, audit):
        super().__init__(workspace)
        self.limit, self.audit = limit, audit
        self.last_failure = None

    async def fit(self, provider, model):
        original = pair(self)
        n = memory_tokens(*original)
        if n <= self.limit:
            self.audit('memory-capacity.jsonl', {'status': 'fits', 'tokens': n, 'limit': self.limit})
            return True
        messages = [{'role': 'system', 'content': (
            'You are editing files under a storage capacity constraint. Rewrite the supplied '
            'MEMORY.md and HISTORY.md contents to fit their combined storage limit. '
            'Choose your own organization and what information to retain. Do not invent facts. '
            'No new task instruction is being supplied. Call pack_storage with both complete files. '
            f'The hard combined maximum is {self.limit} o200k_base tokens. Aim for at most {int(self.limit * .70)} tokens to leave a measured safety margin.')},
            {'role': 'user', 'content': json.dumps(dict(zip(('MEMORY.md', 'HISTORY.md'), original)))}]
        for attempt in range(2):
            response = await provider.chat(messages=messages, tools=PACK_TOOL, model=model,
                                           tool_choice='required')
            calls = response.tool_calls or []
            data = calls[0].arguments if len(calls) == 1 and calls[0].name == 'pack_storage' else None
            valid = (response.finish_reason in ('stop', 'tool_calls') and isinstance(data, dict)
                     and set(data) == {'memory', 'history'}
                     and all(isinstance(v, str) for v in data.values()))
            size = memory_tokens(data['memory'], data['history']) if valid else None
            accepted = valid and size <= self.limit
            self.audit('memory-capacity.jsonl', {'status': 'packed' if accepted else 'rejected',
                'attempt': attempt + 1, 'input_tokens': n, 'output_tokens': size, 'limit': self.limit})
            if accepted:
                write_pair(self, (data['memory'], data['history']))
                return True
            messages = messages[:2] + [{'role': 'user', 'content':
                'Format/capacity resubmission only. Return exactly the two string fields in pack_storage, '
                f'The previous response measured {size} tokens (invalid schema if None); the hard maximum is {self.limit}. Aim for at most {int(self.limit * .60)} combined tokens. No new facts or task answers are supplied.'}]
        return False

    async def consolidate(self, messages, provider, model):
        original = pair(self)
        self.last_failure = None
        try:
            ok = await super().consolidate(messages, provider, model)
            if not ok:
                write_pair(self, original)
                return False
            if await self.fit(provider, model):
                return True
            self.last_failure = 'persistent_memory_budget_exhausted'
            write_pair(self, original)
            return False
        except Exception as exc:
            write_pair(self, original)
            self.last_failure = str(exc) if str(exc) in {
                'active_context_budget_exceeded', 'persistent_memory_budget_exhausted'} else None
            raise

class LimitedFileTool(Tool):
    """Actor cannot bypass memory limits through session logs or extra files."""
    name = ''
    description = ''
    parameters = {}
    def __init__(self, inner, workspace, store):
        self.inner, self.workspace, self.store = inner, Path(workspace).resolve(), store
        self.name, self.description, self.parameters = inner.name, inner.description, inner.parameters

    async def execute(self, **kwargs):
        value = kwargs.get('path', '')
        p = Path(value)
        p = (self.workspace / p).resolve() if not p.is_absolute() else p.resolve()
        mutable = {self.store.memory_file.resolve(), self.store.history_file.resolve()}
        readable = mutable | {self.workspace / n for n in ('AGENTS.md', 'SOUL.md', 'TOOLS.md', 'TASK.md')}
        if self.name == 'list_dir':
            if p == self.workspace:
                return 'AGENTS.md\nSOUL.md\nTOOLS.md\nmemory/'
            if p == self.workspace / 'memory':
                return 'MEMORY.md\nHISTORY.md'
            return 'Access denied: this directory is outside the shared experiment memory interface.'
        if self.name == 'read_file':
            if p not in readable:
                return 'Access denied: only standard instructions and bounded memory files are readable.'
            return await self.inner.execute(**kwargs)
        if p not in mutable:
            return 'Write denied: persistent writes are limited to memory/MEMORY.md and memory/HISTORY.md.'
        before = pair(self.store)
        try:
            result = await self.inner.execute(**kwargs)
            size = memory_tokens(*pair(self.store))
            if size > self.store.limit:
                write_pair(self.store, before)
                self.store.audit('memory-capacity.jsonl', {'status': 'actor_write_rejected',
                    'tokens': size, 'limit': self.store.limit})
                return f'Write not committed: combined persistent memory exceeds {self.store.limit} tokens. Rewrite more concisely.'
            return result
        except BaseException:
            write_pair(self.store, before)
            raise
