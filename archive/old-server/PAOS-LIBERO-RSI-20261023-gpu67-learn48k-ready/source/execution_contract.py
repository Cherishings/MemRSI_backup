"""Public skill receipts derived only from actual executor output, never goals."""
def receipt(skill, result):
    return {
        'skill': skill,
        'segment_success': bool(result['success']),
        'native_task_complete': bool(result['native_task_complete']),
        'execution_scope': 'partial_until_one_placement' if result.get('stop_after_one') else 'entire_native_task',
        'observed_components': result.get('components_after', {}),
        'scene_observation': result['after']['scene_observation'],
    }


def enrich_history(events, executions):
    """Attach existing executor receipts at the original feedback time only.

    Historical raw logs stay untouched. Align by order, skill and exact scene;
    mismatches are errors, never guessed. No pending/expected task is appended.
    """
    import copy, json
    output, cursor = copy.deepcopy(events), 0
    enriched = []
    for event in output:
        if not event['text'].startswith('Execution feedback: '):
            continue
        raw = json.loads(event['text'].split(': ', 1)[1])
        if cursor >= len(executions):
            raise ValueError('receipt_alignment_missing_execution')
        actual = executions[cursor]; cursor += 1
        if raw['skill'] != actual['skill'] or raw['scene_observation'] != actual['result']['after']['scene_observation']:
            raise ValueError('receipt_alignment_mismatch')
        data = receipt(raw['skill'], actual['result'])
        if 'work_order_id' in raw:data['work_order_id'] = raw['work_order_id']
        event['text'] = 'Execution feedback: ' + json.dumps(data)
        enriched.append(event['id'])
    return output, enriched
