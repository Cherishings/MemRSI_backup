"""Frozen v2 transport and output budgets, identical for every comparison arm."""
GATEWAY_URL = 'http://127.0.0.1:19095/v1'
OUTPUT_CAP = 8192
MAX_REQUEST_ATTEMPTS = 5
MAX_TRANSPORT_RETRIES = 20
RETRY_DELAYS = (5, 10, 20, 30)
OUTPUT_STYLE = ('Keep tool arguments concise. Do not copy observation histories or the conversation into tool arguments. '
                'After tool feedback, use at most two sentences if an acknowledgement is necessary. '
                'Never invent a tool result or execute another physical action before new feedback.')
FORMAT_REPAIR = ('The previous response was incomplete because its output repeated or exceeded the output budget. '
                 'No tool from that response was executed. Return a concise, complete response to the SAME request. '
                 'Use valid JSON tool arguments with brief field values; do not repeat phrases about ending the turn. '
                 'There is no new task instruction or task outcome. Do not infer any task answer from this format notice.')


def retry_transport(error, attempt, total_retries):
    return (error.get('retryable') is True and error.get('output_started') is False
            and error.get('http_status') in (408, 429, 500, 502, 503, 504)
            and error.get('code') != 'generation_output_limit'
            and attempt + 1 < MAX_REQUEST_ATTEMPTS and total_retries < MAX_TRANSPORT_RETRIES)


def error_usage(error):
    usage = error.get('usage')
    if isinstance(usage, dict) and all(isinstance(usage.get(k), int) and usage[k] >= 0
                                     for k in ('prompt_tokens', 'completion_tokens')):
        return usage
    # Only cases known not to have reached inference are zero-cost.
    if error.get('stage') == 'admission' or (error.get('stage') == 'http_connect'
            and error.get('upstream_error_type') in ('SSLError', 'ConnectTimeout')):
        return {'prompt_tokens': 0, 'completion_tokens': 0}
    return None  # A missing bill is not zero, even when no output was received.


def usage_totals(output):
    import json
    success = output/'model-trace.jsonl'
    errors = output/'model-errors.jsonl'
    rows = [json.loads(x)['response'].get('usage', {}) for x in success.read_text().splitlines()] if success.exists() else []
    rows += [error_usage(json.loads(x)) for x in errors.read_text().splitlines()] if errors.exists() else []
    valid = [u for u in rows if isinstance(u, dict) and all(isinstance(u.get(k), int) for k in ('prompt_tokens', 'completion_tokens'))]
    return {'model_input_tokens': sum(u['prompt_tokens'] for u in valid),
            'model_output_tokens': sum(u['completion_tokens'] for u in valid),
            'model_cost_complete': bool(rows) and len(valid) == len(rows),
            'model_cost_unknown_requests': len(rows) - len(valid)}
