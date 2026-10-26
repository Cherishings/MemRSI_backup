"""Task-facing text separated from scoring. No target enters continuation input."""
import hashlib,json

def initial_instruction(history):
    if history not in ('one_first','two_first'):raise ValueError('unknown_history')
    order=('service table one, then service table two' if history=='one_first' else
           'service table two, then service table one')
    return ('Prepare both service tables. At service table one, put the white mug on the plate and '
            'chocolate pudding to the right of the plate. At service table two, put the white mug '
            'on the left plate and yellow-and-white mug on the right plate. '
            'Do them in this order: '+order+'.')

def continuation_input(observations):
    # Stable ordering of both views; no current station, target, task status or sequence hint.
    assert set(observations)=={'station_one','station_two'}
    return 'Continue. Current scene observations: '+json.dumps(observations,sort_keys=True,separators=(',',':'))

def expected_order(history):
    return ['serve_table_one','serve_table_two'] if history=='one_first' else ['serve_table_two','serve_table_one']

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def compare_pair(rows):
    by={r['history']:r for r in rows}
    complete=set(by)=={'one_first','two_first'}
    snapshots=[r.get('recovery_snapshot') for r in rows]
    both_reached=complete and all(snapshots)
    same_now=bool(both_reached and snapshots[0]['current_input_sha256']==snapshots[1]['current_input_sha256']
                  and snapshots[0]['station_state_sha256']==snapshots[1]['station_state_sha256'])
    return {'both_cases_terminal':complete,'both_reached_first_checkpoint':bool(both_reached),
            'identical_task_facing_current_input':same_now,
            'both_first_choices_correct':bool(same_now and all(r.get('first_return_correct') is True for r in rows)),
            'both_full_workflows_successful':bool(same_now and all(r['status']=='success' for r in rows))}
