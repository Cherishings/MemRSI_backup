"""Two sequential component-credit rounds; sealed validation; no test feedback."""
import asyncio,copy,json,hashlib
from pathlib import Path
from durable_queue import read,unique_attempts
from parallel_runtime import ParallelExperiment
from stream_design import development_rows,SEED_PROCEDURES,compile_procedures
from memory_policy import digest
from targeted_requests import cached_structured
from structured_feedback import CRITIC
from feedback_learning import screen_generic
from targeted_evidence import fixtures,diagnose,packet
from targeted_probe import paired,select
from optimizer_context import clip
from replay import dump
from model_provider import LEARNING_LEDGER

class DevelopmentExperiment(ParallelExperiment):
    def __init__(self,*args,old_learning,**kwargs):
        super().__init__(*args,**kwargs);self.old_learning=Path(old_learning)
    def batch(self,rows,policies,output,strict_technical=False,inherited=()):
        extra=[];policy=read(policies['memrsi']) if 'memrsi' in policies else None
        if policy is not None:
            for old in sorted(self.old_learning.glob('round-*')):
                if read(old/'parent-policy.json')==policy:
                    extra.extend(read(old/'physical/attempts.json',[]))
        ids={r['trial_id'] for r in rows};extra=[dict(r,inherited=True) for r in extra if r['trial_id'] in ids]
        dump(Path(output)/'reuse-audit.json',{'same_policy_attempts':len(extra),'max_attempts':3,'new_policy_is_new_treatment':not bool(extra)})
        return super().batch(rows,policies,output,strict_technical,tuple(inherited)+tuple(extra))

def small_packet(f):
    p=packet(f)
    for k,cap in [('archive_input_excerpt',400),('memory_before_excerpt',200),('memory_after_excerpt',350),('selected_evidence_excerpt',200),('request',150)]:p[k]=clip(p[k],cap)
    return p

def bounded_proposal_data(target,current,ds,fs,credits):
    from optimizer_context import prepare
    data={'target_operator':target,'parent':current,'diagnostic_hypotheses':ds,
          'development_evidence':[small_packet(f) for f in fs],
          'previous_component_effects':credits}
    for cap in (350,200,100,48):
        for row in data['development_evidence']:
            for k in ('archive_input_excerpt','memory_before_excerpt','memory_after_excerpt','selected_evidence_excerpt','request'):
                row[k]=clip(row[k],cap)
        try:
            _,_,audit=prepare('Component proposal '+('x '*200),data,target_schema(target))
            if audit['after_tokens']<8200:return data
        except ValueError:pass
    raise ValueError('proposal_evidence_cannot_fit')

def target_schema(target):
    return {'type':'object','properties':{target:{'type':'string','minLength':1,'maxLength':1600},
         'rationale':{'type':'string','maxLength':600}},'required':[target,'rationale'],'additionalProperties':False}

def patched(parent,submission,target):
    if set(submission)!={target,'rationale'}:raise ValueError('single_operator_required')
    value=copy.deepcopy(parent);value[target]=submission[target]
    compiled=compile_procedures(value);screen_generic(compiled)
    other='update' if target=='guidance' else 'guidance'
    if value[other]!=parent[other]:raise AssertionError('unrelated_operator_changed')
    return value,compiled

async def run(out,experiment,budget,old_learning):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'report.json').exists():return read(out/'report.json')
    old_learning=Path(old_learning)
    if not (out/'learning-call-ledger.json').exists():
        ledger=read(old_learning/'learning-call-ledger.json',{'calls':0,'limit':6000});dump(out/'learning-call-ledger.json',ledger)
        dump(out/'inherited-learning-budget.json',{'source':str(old_learning),'ledger':ledger,'budget_not_reset':True})
    LEARNING_LEDGER.set(out/'learning-call-ledger.json')
    current=copy.deepcopy(SEED_PROCEDURES);credits=[];promotions=0
    manifest={'development_ids':[r['trial_id'] for r in development_rows()[:16]],
      'reserved_validation_ids':[r['trial_id'] for r in development_rows()[16:]],
      'cycles':2,'episodes_per_cycle':8,'proposals_per_cycle':2,'repetitions':3,
      'operator_space':['guidance','update'],'one_operator_changed_per_candidate':True,
      'minimum_net_correct_gain':1,'promotion_is_exploratory_not_significance':True,'persistent_regression_guard':'parent correct in all replicates and candidate wrong in all',
      'cost_metric':'logical calls including failed attempts; incomplete token usage separately retained','cost_ratio_max':1.5,'technical_attempts_max':3,'validation_feedback_to_proposer':False,'pilot_cycle0_reused':True,
      'test_feedback_to_proposer':False,'capacity_actor_and_scoring_unchanged':True}
    previous=read(out/'manifest.json')
    if previous is not None and previous!=manifest:raise RuntimeError('design_changed')
    dump(out/'manifest.json',manifest)
    for cycle in range(2):
        root=out/f'cycle-{cycle}';root.mkdir(exist_ok=True);parent=compile_procedures(current)
        dump(root/'parent-policy.json',parent)
        rows=[dict(r,gpu=2) for r in development_rows()[cycle*8:(cycle+1)*8]]
        experiment.state('targeted_development',cycle=cycle,promotions=promotions)
        physical=await asyncio.to_thread(experiment.batch,rows,{'memrsi':root/'parent-policy.json'},root/'physical')
        fs,excluded=fixtures(physical);dump(root/'fixture-audit.json',{'eligible':[f['id'] for f in fs],'excluded':excluded,'planned':8})
        done=read(root/'selection.json')
        if done:
            if done['parent_hash']!=digest(parent):raise RuntimeError('parent_changed')
            current=done['selected_procedures'];promotions+=int(done['accepted']);credits.append(done['credit']);continue
        experiment.state('targeted_diagnosis',cycle=cycle,promotions=promotions)
        ds=await diagnose(fs,root/'diagnoses',experiment.wait_gateway);dump(root/'diagnoses.json',ds)
        # Actor-use hypotheses do not justify modifying archival storage.
        targets=[] if ds and all(d['locus']=='actor_usage' for d in ds) else ['guidance','update']
        candidates=[]
        if not fs:targets=[]
        for target in targets:
            folder=root/target;folder.mkdir(exist_ok=True)
            experiment.state('targeted_proposal',cycle=cycle,operator=target)
            submission=await cached_structured(folder/'proposal',
              'Improve exactly one operator of a long/short memory interface. '
              'Guidance selects at most five exact source fragment IDs; Update modifies native archival writing. '
              'Use quote-grounded hypotheses and actual component effects from earlier cycles. '
              'Do not claim a hypothesis is proven. Protect successful cases. '
              'Return one complete generic procedure and rationale. Do not encode task IDs, objects, action orders, '
              'benchmark names or answer rules. Never force finish/continuation or override user changes. '
              'Do not alter the other operator. Preserve the parent if evidence does not support a change.',
              bounded_proposal_data(target,current,ds,fs,credits),target_schema(target),experiment.wait_gateway)
            procedures,candidate=patched(current,submission,target)
            critic=await cached_structured(folder/'critic',
                'Check generic memory management rules: no concrete task answers or benchmark identifiers, '
                'preserve user authority, no hard rule forcing continuation or finish.',procedures,CRITIC,experiment.wait_gateway)
            if not all(critic[k] for k in ('generic','no_task_answers','preserves_user_authority')) or candidate==parent:
                dump(folder/'screen.json',{'accepted':False,'reason':'critic_or_unchanged'});continue
            dump(folder/'candidate-policy.json',candidate)
            experiment.state('targeted_component_intervention',cycle=cycle,operator=target)
            probes=await paired(fs,folder/'probes',parent,candidate,budget,experiment.wait_gateway)
            score=select(probes);dump(folder/'effect.json',score)
            candidates.append({'operator':target,'procedures':procedures,'effect':score})
        accepted=[x for x in candidates if x['effect']['accepted']]
        chosen=max(accepted,key=lambda x:(x['effect']['gain_fraction'],-x['effect']['logical_calls']['candidate'])) if accepted else None
        if chosen:current=chosen['procedures'];promotions+=1
        credit={'cycle':cycle,'effects':[dict(operator=x['operator'],**x['effect']) for x in candidates],
                'chosen_operator':chosen['operator'] if chosen else None,'diagnoses_are_hypotheses':True}
        done={'accepted':chosen is not None,'parent_hash':digest(parent),'selected_procedures':current,'credit':credit}
        dump(root/'selection.json',done);credits.append(credit)
        dump(out/'progress.json',{'completed_development':(cycle+1)*8,'promotions':promotions,'phase':'development'})
    # Do not rerun the fixed seed under an RSI label if nothing changed.
    dump(out/'candidate-procedures.json',current);dump(out/'candidate-policy.json',compile_procedures(current))
    if promotions==0:
        report={'status':'no_accepted_update','promotions':0,'heldout_should_run':False,'reason':'do_not_relabel_seed_as_evolution'}
        dump(out/'report.json',report);return report
    # Freeze before examining independent validation. Validation never rewrites a rule.
    report={'status':'candidate_ready_for_validation','promotions':promotions,
            'candidate_hash':digest(compile_procedures(current)),'credits':credits,'heldout_should_run':False}
    dump(out/'development-report.json',report)
    return report
