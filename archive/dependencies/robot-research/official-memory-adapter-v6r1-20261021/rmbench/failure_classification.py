"""Capacity/protocol failures are retained actor outcomes, never retry triggers."""
AGENT_ERRORS = frozenset({
    'active_context_budget_exceeded', 'persistent_memory_budget_exhausted',
    'native_session_archival_failed', 'action_protocol_failure',
    'guidance_protocol_failure', 'guidance_review_protocol_failure',
    'guidance_grounding_failure', 'invalid_guidance', 'agent_call_budget_exhausted',
    'generation_output_limit', 'delta_update_protocol_failure', 'delta_memory_schema',
})
TRANSPORT_ERRORS = frozenset({'provider_error', 'model_admission_wait_timeout'})


def classify(error, phase):
    code = str(error)
    if code in AGENT_ERRORS:
        return 'agent_failure', code
    if code in TRANSPORT_ERRORS or type(error).__name__ in {
            'APIConnectionError', 'APITimeoutError', 'ConnectionError', 'TimeoutError',
            'HTTPError', 'URLError'}:
        return 'technical_failure', code if code in TRANSPORT_ERRORS else 'transport_failure'
    if phase in {'controller', 'simulator'}:
        return 'technical_failure', 'controller_or_simulator_interface_failure'
    return 'unclassified_failure', 'unclassified_exception'
