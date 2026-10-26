"""Paired history problems with an identical current world in both histories."""
from pair_protocol import expected_order
CASES=('resume','delay','revise','cancel')

def protocol(case,history,jobs):
    if case not in CASES or jobs not in (12,16,24,32):raise ValueError('invalid condition')
    order=expected_order(history)
    labels={'serve_table_one':'service table one','serve_table_two':'service table two'}
    first,second=map(labels.get,order)
    scope=('Prepare table one by placing its white mug on the plate and pudding to its right; '
           'prepare table two by placing its white mug on the left plate and yellow-and-white mug on the right plate. ')
    partial=case!='delay'
    if partial:
        initial=(scope+'Start table one now, but pause as soon as the first object is safely placed. '
                 'The controller will pause the native skill there. After the kitchen work orders, '
                 'complete '+first+' before '+second+'. Already completed placements do not need to be repeated.')
    else:
        initial=(scope+'Reserve both table services for closing time, after all %d kitchen work orders. '%jobs+
                 'At that time complete '+first+' before '+second+'. Do not start either table early.')
    updates={};remaining=list(order)
    if case=='revise':
        updates[jobs//3]=('Change the remaining service priority: after the kitchen work, complete '+second+
                         ' before '+first+'. This replaces the previous priority; both unfinished services are required.')
        remaining=list(reversed(order))
    elif case=='cancel':
        updates[jobs//3]=('Cancel all remaining work on '+second+'. Do not undo placements already made. '
                         'No replacement is requested; other outstanding requirements remain valid.')
        remaining=order[:1]
    return dict(case=case,initial=initial,pre_actions=['serve_table_one'] if partial else [],partial_initial=partial,
        interruption='Please handle %d kitchen work orders, one at a time, before continuing table service.'%jobs,
        updates_after_order=updates,expected_remaining=remaining,planned_rollovers=jobs//2,
        planned_physical_tasks=jobs+len(remaining),planned_memory_checkpoints=len(remaining)+1,
        expected_history_dependence='Both histories have the same partial table-one prefix (or same untouched tables for delay), same interruption work, different required first recovery action.')

def classify_error(chosen,expected,seen,cancelled):
    if chosen=='finish' and expected!='finish':return 'premature_finish'
    if chosen in cancelled:return 'executed_cancelled_requirement'
    if chosen in seen:return 'repeated_completed_requirement'
    if chosen=='execute_order':return 'requested_completed_kitchen_order'
    if expected=='finish':return 'extra_action_after_completion'
    return 'wrong_valid_requirement_order'
