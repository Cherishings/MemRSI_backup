"""Two feedback rounds; separate G/U intervention credit, held-out audit once.

This is a research candidate, not a claim of novelty or guaranteed improvement.
Historical windows are developer data, not autonomous physical successes.
"""
import asyncio, copy, json
from pathlib import Path
from replay import dump
from learning_v13 import prepare, optimizer_budget
from feedback_learning import batch, improves, evidence, screen_generic
from memory_design import SEED, MANDATORY, OPTIONAL, DESIGN_SCHEMA, validate_design, policy
from memory_policy import combinations, digest, operator_credit
from structured_feedback import structured, CRITIC

def compact(s):
    return {k:v for k,v in s.items() if k!='rows'}

def select(parent, variants):
    eligible=[(s['correct'], -int(k=='joint'), -s['tokens'], k)
              for k,s in variants.items() if improves(parent,s)]
    return max(eligible)[-1] if eligible else None

def merge_design(parent,candidate,variant):
    d=copy.deepcopy(parent)
    if variant in ('guidance_only','joint'):d['read_focus']=candidate['read_focus']
    if variant in ('update_only','joint'):
        d['fields']=candidate['fields'];d['retention_focus']=candidate['retention_focus']
    return validate_design(d)

def feedback_packet(fixtures):
    # Optimizer-only, explicitly truncated snippets. Never sent to the actor.
    out=[]
    for f in evidence(fixtures):
        out.append({k:v for k,v in f.items() if k not in ('recorded_archive_input','recorded_long_memory','source_guidance')})
        out[-1].update(memory_excerpt=f['recorded_long_memory'][:1800],
                      archive_tail_excerpt=json.dumps(f['recorded_archive_input'],ensure_ascii=False)[-1800:],
                      guidance_excerpt=str(f['source_guidance'])[:700],excerpts_truncated=True)
    return out

async def run(out,resume=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    dev,valid=prepare()
    dump(out/'fixtures.json',{'development':dev,'validation':valid})
    dump(out/'manifest.json',{'rounds':2,'proposals_per_round':1,'repeats_per_window':2,
      'development_windows':len(dev),'validation_windows':len(valid),
      'learned':['record fields','retention focus','evidence-selection focus'],
      'selection':'strict paired development gain, per-case nonregression, complete valid accounting, <=1.5x tokens',
      'validation':'once after both rounds; never feedback to proposer',
      'scope':'restored decision and single-archive windows, not full physical runs',
      'max_optimizer_calls_soft':1200,'test_feedback_to_optimizer':False,
      'candidate_without_validated_gain':'label unvalidated; independent transfer still runs'})
    design=copy.deepcopy(SEED);parent=policy(design)
    dump(out/'seed-policy.json',parent)
    dump(out/'progress.json',{'status':'development_seed'})
    prior_calls=0;restored=None
    if resume:
        from resume_v15 import restore
        restored=restore(resume,out,{'development':dev,'validation':valid})
        baseline,first,recovered,prior_calls=restored
    else:baseline=await batch(dev,out/'seed-development',parent)
    if baseline['invalid'] or not baseline['cost_complete']:raise RuntimeError('baseline_probe_invalid')
    current=baseline;rounds=[];promotions=0;last_candidate=None
    if restored:
        rounds=[first];last_candidate=policy(first['proposed_design'])
    def budget():
        calls=prior_calls+sum(json.loads(p.read_text()).get('calls',0) for p in out.rglob('calls.json'))
        if calls>1200:raise RuntimeError('learning_call_budget_exhausted')
    for idx in range(1 if restored else 0,2):
        folder=out/f'round-{idx}';folder.mkdir();budget()
        dump(out/'progress.json',{'status':'proposing','round':idx,'promotions':promotions})
        if restored:
            proposal=recovered
            dump(folder/'proposal/value.json',proposal)
        else:
            proposal=await structured(folder/'proposal',
              'Evolve a bounded long/short memory system from real execution feedback. '
              'Long-memory guidance selects source evidence for short-term decisions; short-term update '
              'decides how to preserve verified progress, unresolved requirements and revisions. '
              'Change record fields/read_focus/retention_focus, not task goals or the physical policy. '
              'Use prior round measured update-only, guidance-only and joint effects to correct your design. '
              'Do not encode concrete objects, tables, task tools, sequences, answers, evaluator access, '
              'or a hard rule forcing continuation. Do not override users. Only propose general memory procedures.',
              {'parent':design,'mandatory_fields':MANDATORY,'optional_fields':OPTIONAL,
               'development_feedback':feedback_packet(dev),'current_scores':compact(current),'earlier_rounds':rounds},DESIGN_SCHEMA)
        row={'round':idx,'proposed_design':proposal,'parent_sha256':digest(parent)}
        try:validate_design(proposal);candidate=policy(proposal);screen_generic(candidate)
        except ValueError:
            row['decision']='invalid_or_nongeneric';rounds.append(row);dump(folder/'decision.json',row);continue
        if digest(candidate)==digest(parent):
            row['decision']='unchanged';rounds.append(row);dump(folder/'decision.json',row);continue
        critic=await structured(folder/'critic','Check genericity and user authority. Reject encoded task answers, sequences and user overrides.',proposal,CRITIC)
        if not all(critic.get(k) is True for k in ('generic','no_task_answers','preserves_user_authority')):
            row['decision']='critic_rejection';rounds.append(row);dump(folder/'decision.json',row);continue
        last_candidate=candidate
        variants=combinations(parent,candidate);scores={}
        for name in ('update_only','guidance_only','joint'):
            dump(out/'progress.json',{'status':'paired_development','round':idx,'variant':name,'promotions':promotions})
            scores[name]=await batch(dev,folder/name,variants[name]);budget()
        all_scores=dict(scores,old=current)
        row['scores']={k:compact(v) for k,v in all_scores.items()}
        row['credit']=operator_credit({k:{'passed':[r['correct'] for r in s['rows']]} for k,s in all_scores.items()})
        row['credit']['valid']=all(not s['invalid'] and s['cost_complete'] for s in all_scores.values())
        chosen=select(current,scores)
        row['decision']=chosen or 'retain_parent_no_paired_gain'
        if chosen:
            design=merge_design(design,proposal,chosen);parent=policy(design)
            assert digest(parent)==digest(variants[chosen])
            current=scores[chosen];promotions+=1
            dump(folder/'selected-policy.json',parent);dump(folder/'selected-design.json',design)
        rounds.append(row);dump(folder/'decision.json',row)
    # Choose using development only, then audit on held-out historical sources once.
    final=parent if promotions else last_candidate
    report={'status':'candidate_ready' if final else 'no_changed_candidate','development_promotions':promotions,
            'rounds':rounds,'validated_gain':False,'physical_transfer_gain':False,
            'scope':'window learning only; no autonomous physical claim'}
    if final:
        dump(out/'candidate-policy.json',final)
        dump(out/'candidate-freeze.json',{'sha256':digest(final),'selected_before_validation':True,
              'selection':'development_promoted' if promotions else 'last_generic_proposal_for_diagnostic_test'})
        dump(out/'progress.json',{'status':'independent_window_audit','promotions':promotions})
        a=await batch(valid,out/'seed-validation',policy(SEED))
        b=await batch(valid,out/'candidate-validation',final);budget()
        report.update(validation_seed=compact(a),validation_candidate=compact(b),validated_gain=improves(a,b))
    dump(out/'report.json',report);dump(out/'progress.json',{'status':report['status'],'promotions':promotions})
    return report
