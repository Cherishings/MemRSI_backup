"""Development-only planning and answer-free local-edit format diagnostics.

No model/GPU calls; no policy mutations or relaxation of the original gate.
A new registered study must explicitly consume this module; old studies stay frozen.
"""
import copy,hashlib,json

def development_plan(sources, rows, parent_sha, repeats=2):
    if not sources or any(s.get('split')!='development' for s in sources):raise ValueError('development_only')
    ids=[s['id'] for s in sources]
    if len(set(ids))!=len(ids):raise ValueError('duplicate_source')
    if any(not isinstance(s.get('sha256'),str) or len(s['sha256'])!=64 for s in sources):raise ValueError('source_hash_required')
    expected={(i,r) for i in ids for r in range(repeats)};seen=set();total=correct=0
    for row in rows:
        key=(row['case'],row['repeat'])
        if key not in expected or key in seen:raise ValueError('case_identity_mismatch')
        if row.get('split')!='development' or row.get('policy_sha256')!=parent_sha:raise ValueError('split_or_parent_mismatch')
        if row.get('technical_failure') is not False:raise ValueError('technical_or_unknown_row')
        c,p=row['correct'],row['planned']
        if type(c)!=int or type(p)!=int or not 0<=c<=p:raise ValueError('invalid_checkpoint_counts')
        seen.add(key);correct+=c;total+=p
    if seen!=expected:raise ValueError('incomplete_registered_development')
    # All fixed sources remain present, including successful controls.
    return {'sources':copy.deepcopy(sources),'pairs':len(expected),'parent_correct':correct,'planned':total,
            'max_correct_gain':total-correct,'proposal_allowed':correct<total,
            'reason':'measurable_headroom' if correct<total else 'strict_gain_unreachable_no_proposal',
            'source_policy_sha256':parent_sha,'all_registered_controls_preserved':True,
            'selection_gate_changed':False}

def contract_feedback(parent, patch):
    errors=[]
    if not isinstance(patch,dict):return [{'field':'submission','code':'object_required'}]
    allowed={'target','anchor','replacement','rationale'}
    for k in sorted(set(patch)-allowed):errors.append({'field':k,'code':'additional_field'})
    for k in ('target','replacement','rationale'):
        if k not in patch:errors.append({'field':k,'code':'required'})
    for k,limit in [('target',20),('anchor',450),('replacement',1200),('rationale',1200)]:
        if k not in patch:continue
        value=patch[k]
        if not isinstance(value,str):errors.append({'field':k,'code':'string_required'});continue
        if k!='anchor' and not value.strip():errors.append({'field':k,'code':'nonempty_required'})
        if len(value)>limit:errors.append({'field':k,'code':'max_characters','observed':len(value),'limit':limit,'excess':len(value)-limit})
    target=patch.get('target')
    if not isinstance(target,str) or target not in ('guidance','update'):errors.append({'field':'target','code':'allowed_guidance_or_update'});return errors
    old=parent[target];anchor=patch.get('anchor','');replacement=patch.get('replacement')
    if not isinstance(anchor,str) or not isinstance(replacement,str):return errors
    max_anchor=min(450,int(len(old)*.35))
    if len(anchor)>max_anchor:errors.append({'field':'anchor','code':'local_edit_limit','observed':len(anchor),'limit':max_anchor})
    if anchor and old.count(anchor)!=1:errors.append({'field':'anchor','code':'unique_exact_anchor_required'});return errors
    new=old.replace(anchor,replacement,1) if anchor else old+'\n'+replacement
    budget=1600-len(old)+(len(anchor) if anchor else -1)
    if len(new)>1600:errors.append({'field':'replacement','code':'final_operator_limit','final_observed':len(new),'final_limit':1600,'max_replacement_for_this_anchor':max(0,min(1200,budget))})
    if new.strip()==old.strip():errors.append({'field':'replacement','code':'unchanged_edit'})
    return errors

async def bounded_proposal(request, parent, validate, audit):
    """request uses existing provider/ledger. One original + one format resubmission.
    Transport exceptions propagate. No extra technical attempt or automatic text repair.
    """
    feedback=None
    for number in range(2):
        patch=await request(feedback)
        errors=contract_feedback(parent,patch)
        if not errors:
            candidate=validate(parent,patch) # original generic-policy screen and compiler
            audit.append({'submission':number+1,'format_valid':True})
            return candidate
        audit.append({'submission':number+1,'format_valid':False,'errors':errors})
        feedback={'format_only':True,'errors':errors,'same_intended_edit_required':True,
                  'new_task_evidence':False,'remaining_resubmissions':1-number}
    return None
