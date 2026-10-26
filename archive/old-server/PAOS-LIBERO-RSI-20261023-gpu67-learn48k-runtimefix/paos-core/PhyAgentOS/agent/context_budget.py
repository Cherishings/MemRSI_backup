"""Bound live tool-result context without altering the archived conversation."""
import json

from PhyAgentOS.utils.helpers import estimate_prompt_tokens


def request_tokens(messages, tools):
    # Include function-call arguments and reasoning, which the basic text estimator
    # omits. Images receive a conservative allowance rather than tokenizing base64.
    normalized = []
    images = 0
    for message in messages:
        content = message.get('content')
        if isinstance(content, list):
            images += sum(isinstance(p, dict) and p.get('type') == 'image_url' for p in content)
        normalized.append(message)
        meta = {k: message[k] for k in ('tool_calls', 'tool_call_id', 'reasoning_content') if message.get(k)}
        if meta:
            normalized.append({'role': 'user', 'content': json.dumps(meta, ensure_ascii=False)})
    count = estimate_prompt_tokens(normalized, tools)
    if not count:
        count = (sum(len(str(m.get('content') or '')) for m in normalized) + len(str(tools))) // 3
    return count + len(messages) * 8 + images * 1024


def budget_tool_context(messages, tools, limit):
    """Keep system/user instructions and all call/result identities intact.

    Only request-local copies of older bulky tool bodies are shortened. Original
    messages remain available for the session archive and verifier evidence.
    """
    request = [dict(m) for m in messages]
    if request_tokens(request, tools) <= limit:
        return request
    indices = [i for i, m in enumerate(request) if m.get('role') == 'tool' and isinstance(m.get('content'), str)]
    for protected in (2, 0):
        candidates = indices[:-protected] if protected else indices
        for cap in (6000, 2000, 600):
            for i in candidates:
                original = messages[i]['content']
                if len(original) <= cap or len(request[i]['content']) <= cap:
                    continue
                half = cap // 2
                request[i]['content'] = (
                    original[:half] + '\n[Older tool output shortened for context; '
                    'retrieve the task or file again if details are needed.]\n' + original[-half:]
                )
                if request_tokens(request, tools) <= limit:
                    return request
    if request_tokens(request, tools) > limit:
        raise ValueError('Live context exceeds its input budget even after tool-result compaction')
    return request
