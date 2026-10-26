"""Immutable split and bounded executable G/U procedures for sequential development."""
import itertools, json, random
from memory_design import SEED,policy,update_instruction
from memory_policy import validate
from feedback_protocol import old_histories,v13_histories,histories,transfer_histories,DEVELOPMENT_HISTORIES

GUIDE_SEED=(
 'Select up to five evidence fragment IDs for the acting agent from supplied long task memory, '
 'current short context and current request. Return IDs only. The program copies those exact '
 'source fragments to the actor. Prefer task identity together with relevant status, priority, '
 'changed requirements or feedback. Neighboring fragments may belong to one record. '
 'Do not generate an action or translate tasks into tools. Empty selection is allowed. '
 'Original requests and feedback govern; remembered claims can be wrong. Focus: '+SEED['read_focus'])
SEED_PROCEDURES={'guidance':GUIDE_SEED,'update':update_instruction(policy(SEED)['update'])}
SCHEMA={'type':'object','properties':{
 'guidance':{'type':'string','minLength':1,'maxLength':1600},
 'update':{'type':'string','minLength':1,'maxLength':1600},
 'rationale':{'type':'string','maxLength':700}},
 'required':['guidance','update'],'additionalProperties':False}

def compile_procedures(d):
    if not {'guidance','update'}<=set(d) or set(d)-{'guidance','update','rationale'}:raise ValueError('rule_fields')
    for k in ('guidance','update'):
        if not isinstance(d[k],str) or not d[k].strip() or len(d[k])>1600:raise ValueError('rule_length')
    return validate({'schema':1,
        'guidance':json.dumps({'kind':'procedure_guidance_v2','procedure':d['guidance']},sort_keys=True),
        'update':json.dumps({'kind':'procedure_update_v2','procedure':d['update']},sort_keys=True)})

def development_histories():
    used=set(old_histories()+v13_histories()+histories()+transfer_histories())|set(DEVELOPMENT_HISTORIES)
    values=[''.join(x) for x in itertools.permutations('ABCDE') if ''.join(x) not in used]
    random.Random(20261012016).shuffle(values)
    return values[:10]

def development_rows():
    return [dict(trial_id=f'dev-{i:02d}',condition=f'dev-{i:02d}',history=h,init=init,
        repeat=0,arm='memrsi',gpu=i%3)
        for i,(h,init) in enumerate((h,j) for h in development_histories() for j in (0,1))]

def heldout_rows(comparison_schedule,transfer_schedule):
    # Deterministic manifest-only pairing; never filter using success/failure.
    conditions=[]
    for dataset,rows in [('comparison',comparison_schedule),('transfer',transfer_schedule)]:
        for r in rows:
            if r['arm']!='native':continue
            conditions.append(dict(dataset=dataset,baseline_trial_id=r['trial_id'],**{k:r[k] for k in ('condition','history','init','repeat')}))
    if len(conditions)!=48:raise ValueError('unexpected_heldout_count')
    if {r['history'] for r in conditions}&set(development_histories()):raise ValueError('split_overlap')
    result=[]
    for i,r in enumerate(conditions):
        for arm in (('before','evolved') if i%2==0 else ('evolved','before')):
            result.append(dict(r,trial_id=f"{r['dataset']}/{r['condition']}-r{r['repeat']}/{arm}",arm=arm,gpu=i%3))
    return result
