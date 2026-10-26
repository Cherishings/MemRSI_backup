"""Unconnected development prototype. No execution, memory writes or task oracle."""
import json
from pathlib import Path

PROCEDURE = (
    'Advise the acting agent using the supplied public evidence and execution API. '
    'Identify the current request and distinguish revisions, cancellations, commitments and actual receipts. '
    'Recommend one next action only when supported; otherwise abstain and explain the uncertainty. '
    'Cite existing evidence IDs for your recommendation. Archived summaries are fallible. '
    'Do not invent prerequisites, completion, observations, tool capabilities or task authority. '
    'You cannot execute anything. The actor independently decides and may reject your advice.'
)


DELIBERATION = (
    'Take an additional deliberation pass on the supplied public task, history and execution API. '
    'Propose a next action, cite its public evidence and state uncertainty. '
    'You may abstain. Do not execute anything. The acting agent independently decides and may reject your advice.'
)
MODES = {'advisor': PROCEDURE, 'deliberation': DELIBERATION}


def public_messages(messages):
    allowed = ('role', 'content', 'tool_calls', 'tool_call_id', 'name')
    return [{k: m[k] for k in allowed if k in m} for m in messages]


def payload(memory, history, messages, current, action_contract):
    if not action_contract:
        raise ValueError('missing_public_action_contract')
    # Whole public records preserve role/tool linkage; budgets enforced by original provider.
    evidence = {'memory': memory, 'history': history, 'current': current}
    evidence.update({f'short:{i}': m for i, m in enumerate(public_messages(messages))})
    return {'execution_api': action_contract, 'evidence': evidence}


def validate(response, evidence):
    calls = response.tool_calls or []
    if response.finish_reason not in ('stop', 'tool_calls') or len(calls) != 1:
        raise ValueError('advisor_protocol_failure')
    c = calls[0]
    d = c.arguments
    if c.name != 'report_advice' or not isinstance(d, dict) or set(d) != {'recommendation', 'basis_ids', 'uncertainty'}:
        raise ValueError('advisor_protocol_failure')
    if not isinstance(d['recommendation'], str) or not isinstance(d['uncertainty'], str):
        raise ValueError('advisor_protocol_failure')
    ids = d['basis_ids']
    if not isinstance(ids, list) or len(ids) > 5 or any(not isinstance(i, str) or i not in evidence for i in ids):
        raise ValueError('advisor_invalid_citation')
    if len(set(ids)) != len(ids) or (d['recommendation'].strip() and not ids):
        raise ValueError('advisor_invalid_citation')
    return d


class Advisor:
    def __init__(self, provider, workspace, action_contract, mode="advisor"):
        if mode not in MODES: raise ValueError("unknown_advisor_mode")
        self.mode = mode
        self.provider, self.workspace, self.action_contract = provider, Path(workspace), action_contract

    async def guide(self, short_messages, current_message):
        def read(name):
            p = self.workspace / 'memory' / name
            return p.read_text() if p.exists() else ''
        data = payload(read('MEMORY.md'), read('HISTORY.md'), short_messages, current_message, self.action_contract)
        schema = {'type': 'object', 'properties': {
            'recommendation': {'type': 'string', 'description': 'Nonbinding next-action suggestion; empty means abstain.'},
            'basis_ids': {'type': 'array', 'maxItems': 5, 'items': {'type': 'string', 'enum': list(data['evidence'])}},
            'uncertainty': {'type': 'string'}},
            'required': ['recommendation', 'basis_ids', 'uncertainty'], 'additionalProperties': False}
        response = await self.provider.chat(
            messages=[{'role': 'system', 'content': MODES[self.mode]}, {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
            tools=[{'type': 'function', 'function': {'name': 'report_advice', 'description': 'Give advice without executing an action.', 'parameters': schema}}],
            tool_choice='required', model='gpt-5.6-luna')
        advice = validate(response, data['evidence'])
        self.provider._append('advisor-prototype.jsonl', {'native_short_messages': len(short_messages), 'action_contract_present': bool(self.action_contract), 'mode': self.mode, 'advice': advice, 'manual_not_RSI': True, 'physical_execution': False})
        return '# Nonbinding decision advice\nVerify against public observations and requests; you may reject this advice.\n' + json.dumps(advice, ensure_ascii=False)
