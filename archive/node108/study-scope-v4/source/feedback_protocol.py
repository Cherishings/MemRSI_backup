"""Sealed new mission orders; executor and 20-session physical schedule unchanged."""
import itertools,random
from twenty_protocol import plan as original

def old_histories():
    values=[''.join(x) for x in itertools.permutations('ABCDE') if ''.join(x) not in ('ABCDE','EDCBA')]
    random.Random(20261011).shuffle(values)
    return values[:10]

def v13_histories():
    excluded=set(old_histories()) | {'ABCDE','EDCBA'}
    values=[''.join(x) for x in itertools.permutations('ABCDE') if ''.join(x) not in excluded]
    random.Random(20261012).shuffle(values)
    return values[:10]

DEVELOPMENT_HISTORIES=('ABCDE','EDCBA','CABED','CEADB')

def histories():
    excluded=set(old_histories()+v13_histories()) | set(DEVELOPMENT_HISTORIES)
    values=[''.join(x) for x in itertools.permutations('ABCDE') if ''.join(x) not in excluded]
    random.Random(20261014).shuffle(values)
    return values[:10]

def transfer_histories():
    excluded=set(old_histories()+v13_histories()+histories())|set(DEVELOPMENT_HISTORIES)
    values=[''.join(x) for x in itertools.permutations('ABCDE') if ''.join(x) not in excluded]
    random.Random(20261015).shuffle(values)
    return values[:4]

def plan(history):
    from stream_design import development_histories
    if history not in histories()+transfer_histories()+list(DEVELOPMENT_HISTORIES)+development_histories():raise ValueError('unregistered_test_history')
    p=original('alpha');initial=list(history);changed=[initial[1],initial[0]]+initial[2:];final=changed[:2]+changed[3:]+[changed[2]]
    p['initial_message']=p['initial_message'].replace('A, B, C, D, E.',', '.join(initial)+'.')
    p['updates_after_session'][6]='Change the eventual completion priority for tables A through E to: '+', '.join(changed)+'. This replaces the earlier order.'
    p['updates_after_session'][8]='One more priority change: finish the remaining table services in this order: '+', '.join(final)+'. This is the current order.'
    for step in p['sessions']:
        if step['kind']=='recovery':step['expected_private']='serve_'+final[(step['session']-11)//2]
    p.update(history=history,final_order_private=final)
    return p

def schedule(gpus=(0,1,6,7)):
    rows=[];arms=('native','fixed','evolved')
    for repeat in range(2):
        for hi,h in enumerate(histories()):
            for init in (0,1):
                condition=hi*2+init;offset=(condition+repeat)%3
                for arm in arms[offset:]+arms[:offset]:
                    rows.append({'trial_id':f'h{hi:02d}-i{init}-r{repeat}/{arm}','condition':f'h{hi:02d}-i{init}',
                        'history':h,'init':init,'repeat':repeat,'arm':arm,'gpu':gpus[(condition+repeat)%len(gpus)]})
    return rows
