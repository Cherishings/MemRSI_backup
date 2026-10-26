"""24 instruction conditions x2 sampling repeats per arm, fixed qualified physics.
Not 48 independent physical layouts. Never tune rules on these evaluations.
"""
from protocol import case, contract, BUDGET

GAPS = (4, 8, 16)
KINDS = ('resume', 'delayed', 'revision', 'cancellation')


def make_case(platform, gap, kind, reverse, repeat):
    if platform not in ('twin','casa') or gap not in GAPS or kind not in KINDS or repeat not in (0,1):
        raise ValueError('invalid_scale_condition')
    # For revision, the old order is opposite the final requested order.
    plan = case(platform, gap, not reverse if kind == 'revision' else reverse)
    remaining = ['station_A','station_C'] if platform == 'twin' else ['station_C','station_D']
    if reverse: remaining.reverse()
    temporary = [s for s in plan['steps'] if 'work_order' in s]
    if kind == 'delayed':
        plan['steps'][0]['text'] += (
            f' The remaining original services are a deferred request: perform them only after '
            f'all {gap} upcoming temporary work orders have been completed, not earlier.')
    if kind == 'revision':
        temporary[gap//2-1]['text'] += (
            f' Change to the original mission: its remaining services must now be completed in '
            f'this order: {remaining[0]}, then {remaining[1]}. This replaces the earlier order. '
            'Continue processing temporary orders when assigned.')
    elif kind == 'cancellation':
        temporary[gap//2-1]['text'] += (
            ' Cancel the first service in the remaining-service order I originally gave you. '
            'Do not return to finish that service. The second service is still required. '
            'This cancellation has no replacement task. Continue the assigned temporary work.')
        remaining = remaining[1:]
    prefix = [s for s in plan['steps'] if not s['checkpoint']]
    plan['steps'] = prefix + [dict(text='Continue.', expected=t, checkpoint=True, new_session=True)
                             for t in remaining+['finish']]
    plan.update(id=f'{platform}-{kind}-gap{gap}-order{int(reverse)}-r{repeat}', kind=kind,
                reverse=reverse, repeat=repeat, condition=f'{kind}-gap{gap}-order{int(reverse)}',
                paired_history_id=f'{kind}-gap{gap}-r{repeat}',
                planned_checkpoints=len(remaining)+1, planned_workflow_decisions=len(plan['steps']),
                physical_layout='same pilot-qualified seeds/episodes; no new physical layout claim')
    return plan


def cases(platform):
    return [make_case(platform,gap,kind,reverse,repeat)
            for gap in GAPS for kind in KINDS for repeat in (0,1) for reverse in (False,True)]


def libero_gate(report, learning, pairs):
    if report is None:
        return dict(state='waiting', reason='libero_not_finished')
    if report.get('status') != 'completed':
        return dict(state='not_ready', reason='libero_not_completed', status=report.get('status'))
    fixed = (pairs or {}).get('comparisons',{}).get('fixed_vs_evolved',{})
    native = (pairs or {}).get('comparisons',{}).get('native_vs_evolved',{})
    ready = (report.get('physical_runs') == 48 and (learning or {}).get('promotions',0)>0
             and (learning or {}).get('validation',{}).get('passed',False)
             and fixed.get('paired',0)>0 and native.get('paired',0)>0
             and fixed.get('right_success',0)>=fixed.get('left_success',0)
             and native.get('right_success',0)>native.get('left_success',0))
    return dict(state='ready' if ready else 'not_ready',
                reason='qualified_and_restored_paired_performance' if ready else 'libero_improvement_gate_not_met',
                fixed_comparison=fixed, native_comparison=native,
                scope='operational launch criterion, not statistical significance or publication proof')
