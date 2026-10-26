"""Offline, human-authored finite search space; not a learned or accepted policy."""
import copy,json
CATALOG={
 'guidance': {
  'separate_fact_and_summary': 'Before drawing a conclusion, distinguish explicit public requests and correlated receipts from summary assertions; if they conflict, retain the uncertainty rather than treating the summary as a new authorization.',
  'reconcile_before_finish': 'Before concluding that work is complete, reconcile the requested extent with correlated receipts and separately inspect live continuation conditions; a completed segment alone does not settle an outstanding remainder.'},
 'update': {
  'retain_unresolved_extent': 'During consolidation, reconcile each previously live obligation with its correlated receipts; preserve any unresolved extent and activation condition unless applicable cancellation or completion evidence discharges it.',
  'separate_revision_scope': 'During consolidation, separate the scope of a revision from unaffected obligations; preserve the original authorization and continuation conditions of unaffected work and keep unresolved conflicts explicit.'}}

def compile_edit(parent, choice):
 if type(choice) is not dict or set(choice)!=set(CATALOG):raise ValueError('exact_two_choices_required')
 for k in CATALOG:
  if type(choice[k]) is not str or choice[k] not in CATALOG[k]:raise ValueError('unknown_operation')
 result=copy.deepcopy(parent)
 for k in CATALOG:
  value=json.loads(parent[k]);expected='procedure_'+k+'_v2'
  if set(value)!={'kind','procedure'} or value['kind']!=expected:raise ValueError('parent_format')
  addition=CATALOG[k][choice[k]]
  if len(addition)>1200:raise ValueError('local_limit')
  value['procedure']+='\n'+addition
  if len(value['procedure'])>4096:raise ValueError('body_limit')
  result[k]=json.dumps(value,ensure_ascii=False)
 return result

def combinations(parent,choice):
 joint=compile_edit(parent,choice)
 g=copy.deepcopy(parent);g['guidance']=joint['guidance']
 u=copy.deepcopy(parent);u['update']=joint['update']
 return {'parent':copy.deepcopy(parent),'Gedit':g,'Uedit':u,'joint':joint}

SCHEMA={'type':'object','properties':{k:{'type':'string','enum':list(v)} for k,v in CATALOG.items()},'required':list(CATALOG),'additionalProperties':False}
SYSTEM='Select exactly one Guidance operation and one Update operation jointly from the supplied human-authored finite catalog, using only training evidence. Return only the two enum choices. Do not invent text. This is discrete operation selection, not rule-text synthesis. No validation or test evidence is supplied.'
def to_patch(parent,choice):
 compile_edit(parent,choice)
 return {key:value for k in CATALOG for key,value in [(k+'_replacement',CATALOG[k][choice[k]]),(k+'_rationale','Selected human-authored process operation: '+choice[k])]}
