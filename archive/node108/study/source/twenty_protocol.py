"""Private scoring plan and separately authored public events for one serial robot."""
import hashlib,json
TABLES=tuple('ABCDE')
RECOVERY_SESSIONS=(11,13,15,17,19)
KITCHEN_SESSIONS=(2,4,6,8,10,12,14,16,18)
from action_catalog import CONTRACT as TOOLS

def plan(history):
    if history not in ('alpha','beta'):raise ValueError('history')
    initial=list('ABCDE' if history=='alpha' else 'EDCBA')
    update1=[initial[1],initial[0]]+initial[2:]
    final=update1[:2]+update1[3:]+[update1[2]]
    start=('We are serving one kitchen shift. When instructed, begin service at tables A through E, '
           'but pause each after one object is safely placed. Preserve each table and later finish its remaining work. '
           'After the current kitchen work, when asked to continue without another new work order, '
           'finish these tables in this order: '+', '.join(initial)+'. '
           'After all five are completed, serve table F as the final closing task, then end the shift. '
           'A completed placement should not be repeated; a partial placement does not complete a table.')
    updates={4:'Add one closing request: after table F, also serve optional table G.',
       6:'Change the eventual completion priority for tables A through E to: '+', '.join(update1)+'. This replaces the earlier order.',
       8:'One more priority change: finish the remaining table services in this order: '+', '.join(final)+'. This is the current order.',
       10:'Cancel the optional service at table G. There is no replacement for it; other requested work remains valid.'}
    sessions=[]
    for s in range(1,21):
        if s in (1,3,5,7,9):kind='partial';target='serve_'+TABLES[(s-1)//2]
        elif s in KITCHEN_SESSIONS:kind='kitchen';target='execute_order'
        elif s in RECOVERY_SESSIONS:kind='recovery';target='serve_'+final[RECOVERY_SESSIONS.index(s)]
        else:kind='closing';target='serve_F'
        sessions.append({'session':s,'kind':kind,'expected_private':target})
    return {'history':history,'initial_message':start,'updates_after_session':updates,
            'sessions':sessions,'final_order_private':final,'session_count':20,'session_switches':19,
            'partial_count':5,'recovery_count':5,'kitchen_count':9,'planned_checkpoints':7}

def restore_input(observations):
    return 'Continue. Current scene observations: '+json.dumps(observations,sort_keys=True,separators=(',',':'))

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def reference_note(history,completed_jobs=5):
    p=plan(history)
    return ('Mission: complete all required service work and then finish.\n'
       'A,B,C,D,E: each partially served; one placement verified, remaining native component still due.\n'
       'Latest completion order: '+','.join(p['final_order_private'])+'. Prior priority orders are superseded.\n'
       'Optional G cancelled; never perform it. No replacement.\n'
       'After A-E all complete, F remains required as the final closing service.\n'
       f'Kitchen work orders completed: {completed_jobs}; await any new current work orders.\n'
       'Progress must be confirmed by execution receipts; do not redo completed placements.')
