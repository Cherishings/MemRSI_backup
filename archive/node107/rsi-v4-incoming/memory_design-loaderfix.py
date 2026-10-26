"""Evolvable memory representation + evidence selection, never task answers.

All profiles share mandatory task identity and provenance. Learned fields and
focuses are explicit, versioned architectural parameters interpreted by the
same compiler. No evaluator state enters the compiled actor instructions.
"""
import json
MANDATORY=['task_ref','request','status','evidence']
OPTIONAL=['priority','remaining_components','resume_context','supersedes','tool_scope','uncertainty']
SEED={'fields':MANDATORY+['priority','remaining_components','resume_context'],
      'read_focus':'Select records relevant to the current request, incomplete authorized work, and recent changes.',
      'retention_focus':'Preserve current mission and task identities, verified progress, incomplete work and authoritative changes.'}
DESIGN_SCHEMA={'type':'object','properties':{
    'fields':{'type':'array','items':{'type':'string','enum':MANDATORY+OPTIONAL},'minItems':5,'maxItems':10},
    'read_focus':{'type':'string','maxLength':600},'retention_focus':{'type':'string','maxLength':600}},
    'required':['fields','read_focus','retention_focus'],'additionalProperties':False}

def validate_design(d):
    if not isinstance(d,dict) or set(d)!=set(SEED):raise ValueError('design_schema')
    fs=d['fields']
    if not isinstance(fs,list) or not all(isinstance(x,str) for x in fs):raise ValueError('design_fields')
    if not 5<=len(fs)<=10 or len(fs)!=len(set(fs)) or not set(MANDATORY)<=set(fs) or set(fs)-set(MANDATORY+OPTIONAL):raise ValueError('design_fields')
    for k in ('read_focus','retention_focus'):
        if not isinstance(d[k],str) or not d[k].strip() or len(d[k])>600:raise ValueError('design_focus')
    return d

def policy(d):
    validate_design(d)
    return {'schema':1,'guidance':json.dumps({'kind':'evidence_ids_v1','focus':d['read_focus']},sort_keys=True),
        'update':json.dumps({'kind':'task_records_v1','fields':d['fields'],'focus':d['retention_focus']},sort_keys=True)}

def update_instruction(text):
    spec=json.loads(text)
    if spec.get('kind')=='procedure_update_v2':
        value=spec.get('procedure')
        if not isinstance(value,str) or not value.strip() or len(value)>4096:
            raise ValueError('invalid_update_procedure')
        return value
    if spec.get('kind')!='task_records_v1':raise ValueError('memory_design_kind')
    return ('Write MEMORY.md as compact JSON with mission and tasks. Each task is a distinct request INSTANCE. '
        'Use these task fields: '+', '.join(spec['fields'])+'. '
        'task_ref is a public request ID, or originating event and location; keep that reference across pauses. '
        'request is the user-authorized outcome, status is pending/partial/completed/cancelled/uncertain, '
        'evidence cites the originating user event or actual execution feedback. Use null for unknown values. '
        'Only feedback for this same instance changes its completion status. Similar descriptions do not merge '
        'new requests into old completed requests. Continuation resumes existing authorized work; it is not a '
        'new request by itself. User revisions supersede only the affected requirement. '
        'Preserve outstanding work when compressing. Keep historical details concise. HISTORY.md remains '
        'within the same shared total budget, never a second unbounded task list. No private evaluator facts. '
        'Retention focus: '+spec['focus'])
