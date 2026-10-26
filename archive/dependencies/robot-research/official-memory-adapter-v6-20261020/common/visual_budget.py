"""One resource counter for provider enforcement and native tool compaction.

Only the counter is replaced. PAOS's compaction order and archive boundary
selection remain unchanged. A shared pre-guidance reserve is a declared archive
trigger margin, not extra input capacity or an additional model request.
"""
from visual_accounting import accounting_messages
from token_accounting import request_tokens

GUIDANCE_RESERVE_UNITS = 2048
NATIVE_CAPACITY_ERROR = 'Live context exceeds its input budget even after tool-result compaction'


def request_resource_units(messages, tools=None):
    normalized, image_units, _ = accounting_messages(messages)
    return request_tokens(normalized, tools) + image_units


def install_native_counter():
    from PhyAgentOS.agent import context_budget
    context_budget.request_tokens = request_resource_units


def contains_user_message(history, text):
    for message in history:
        if message.get('role') != 'user':
            continue
        content = message.get('content')
        if content == text:
            return True
        if isinstance(content, list) and any(
                part.get('type') == 'text' and part.get('text') == text
                for part in content if isinstance(part, dict)):
            return True
    return False
