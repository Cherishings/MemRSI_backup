"""Development-only evidence collector and one-call local G/U proposer.

This is not a test-time rule updater. Saved evaluation trajectories are rejected
before their content is opened. A returned candidate is never adopted here.
"""
import argparse, asyncio, fcntl, hashlib, json, os, sys
from dataclasses import asdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'common' if (HERE/'common').exists() else HERE/'new_common'))
from adaptation_protocol import SPLITS, complete_records
from source_compatibility import execution_source_matches
from visual_rule_proposal import (build_proposal_request,validate_and_apply_proposal,
                                  policy_sha256,checked_previous_development_feedback,FEEDBACK_SCHEMA)
from learning_budget import charge, LearningBudgetExhausted

class ProposalPaused(RuntimeError):pass

def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    q=p.with_suffix('.tmp');q.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n');q.replace(p)

def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

def text_view(text,limit=4096):
    return {'text':text[:limit],'truncated':len(text)>limit}

def immutable_json(path,value):
    path=Path(path)
    if path.exists():
        if json.loads(path.read_text())!=value:raise ValueError('immutable_artifact_changed')
    else:write(path,value)

def export_manifest(benchmark,parent_policy,cases,output,expected_source_hashes=None):
    """cases maps all registered development seeds to their physical attempts."""
    if set(cases)!=set(SPLITS['development']):raise ValueError('incomplete_development_cases')
    parent=policy_sha256(parent_policy);output=Path(output)
    checked=[]
    # Identity and role checks happen before reading any model or receipt trace.
    for seed,path in sorted(cases.items()):
        path=Path(path);meta=json.loads((path/'started.json').read_text())
        if (meta['benchmark']!=benchmark or type(meta['seed']) is not int or meta['seed']!=seed or
            meta['split']!='development' or meta['method'] not in ('pre','post') or
            meta['policy_sha256']!=parent):raise ValueError('development_identity_mismatch')
        if expected_source_hashes is not None and not execution_source_matches(meta.get('source_hashes'),expected_source_hashes):
            raise ValueError('development_frozen_source_changed')
        row=json.loads((path/'scored-record.json').read_text())
        if any(row.get(key)!=meta.get(key) for key in ('benchmark','seed','split','method','policy_sha256')):
            raise ValueError('development_score_identity_mismatch')
        checked.append((seed,path,row))
    # Relabel cached post executions as a current parent's pre role only after
    # matching the exact policy/source/seed and validating every official row.
    complete_records([dict(row,method='pre') for _,_,row in checked],
                     'development',('pre',),(benchmark,),{'pre':parent})
    manifest={'schema':'visual_rsi_development_v1','split':'development',
              'parent_policy_sha256':parent,'cases':[]}
    for seed,path,row in checked:
        records=lines(path/'actor/public-action-audit.jsonl')
        inputs=lines(path/'actor/public-decision-inputs.jsonl')
        receipts={}
        for receipt in lines(path/'actor/public-receipts.jsonl'):
            key=receipt['preceding_action_event']
            if key in receipts:raise ValueError('duplicate_public_receipt')
            receipts[key]=receipt['public_receipt']
        cid=f'{benchmark}-{seed}';events=[]
        for r in records:
            choice=r['choice'];events.append(dict(event_id=r['event_id'],
                observation=choice['observation'],public_receipt=receipts.get(r['event_id'],''),
                public_action={k:choice[k] for k in ('skill','instruction','reason')}))
        selected=records if len(records)<=8 else records[:4]+records[-4:]
        memory=[dict(event_id=r['event_id'],snapshot_scope=r['snapshot_scope'],
                    **{k:text_view(r[k]) for k in ('memory_before','memory_after','guidance_selected')})
                for r in selected]
        input_selected=inputs if len(inputs)<=8 else inputs[:4]+inputs[-4:]
        public_inputs=[dict(event_id=r['event_id'],public_request=r['public_request'],
                            memory_before=text_view(r['memory_before']),snapshot_scope=r['snapshot_scope'])
                       for r in input_selected]
        evidence=dict(case_id=cid,benchmark=benchmark,seed=seed,split='development',
                      parent_policy_sha256=parent,events=events,memory_evidence=memory,
                      public_decision_inputs=public_inputs,terminal_status=row['status'],
                      official_success=row['official_success'])
        # Do not reconstruct an absent request from task metadata, evaluator
        # classes, private logs or the expected answer. Missing stays unknown.
        first=inputs[0] if inputs else (records[0] if records else None)
        if first is not None and first.get('event_id')==1:
            evidence['public_initial_request']=first['public_request']
        target=output/cid/'evidence.json';immutable_json(target,evidence)
        immutable_json(output/cid/'provenance.json',dict(source=str(path),
              source_decision_sha256=hashlib.sha256((path/'actor/public-action-audit.jsonl').read_bytes()).hexdigest()
                  if (path/'actor/public-action-audit.jsonl').exists() else None,
              source_public_input_sha256=hashlib.sha256((path/'actor/public-decision-inputs.jsonl').read_bytes()).hexdigest()
                  if (path/'actor/public-decision-inputs.jsonl').exists() else None,
              source_receipts_sha256=hashlib.sha256((path/'actor/public-receipts.jsonl').read_bytes()).hexdigest()
                  if (path/'actor/public-receipts.jsonl').exists() else None,
              scope='public actor evidence plus development-only official terminal status and success bit',
              initial_request_truncated=False))
        manifest['cases'].append(dict(case_id=cid,benchmark=benchmark,seed=seed,
            role='development',evidence_file=str(target.relative_to(output))))
    immutable_json(output/'manifest.json',manifest);return output/'manifest.json'

def provider_components():
    sys.path.insert(0,os.environ.get('MEMRSI_FROZEN_CORE','/data/stormlab/xi/paos/worktrees/memrsi-bounded-v2_2'))
    from model_provider import Provider
    from token_accounting import request_tokens
    return Provider,request_tokens

def export_previous_development_feedback(benchmark,round_number,parent_policy,candidate,
                                        paths,selection,current_parent_hash,output,
                                        expected_source_hashes):
    """Collect only the complete, audited development score records of one edit.

    No action trace or environment internals are opened by this collector. A
    cached candidate can become a later parent, so execution role pre/post is
    normalized only after source, policy, seed and the original role agree.
    """
    if benchmark not in ('rmbench','remem') or type(round_number) is not int or round_number!=1:
        raise ValueError('previous_feedback_round_or_benchmark')
    if not isinstance(paths,dict) or set(paths)!={'pre','post'} or any(
            set(paths[m])!=set(SPLITS['development']) for m in paths):
        raise ValueError('previous_feedback_incomplete_cases')
    parent_hash=policy_sha256(parent_policy)
    ids=[f'{benchmark}-{s}' for s in SPLITS['development']]
    checked=validate_and_apply_proposal(parent_policy,candidate['proposal'],ids,parent_hash)
    if checked!=candidate:raise ValueError('previous_feedback_candidate_changed')
    policies={'pre':parent_hash,'post':checked['candidate_policy_sha256']}
    rows=[];provenance=[]
    # Metadata checks for every case happen before any scored record is read.
    metadata=[]
    for method in ('pre','post'):
        for seed,path in sorted(paths[method].items()):
            path=Path(path);meta=json.loads((path/'started.json').read_text())
            if (meta.get('benchmark')!=benchmark or type(meta.get('seed')) is not int or meta['seed']!=seed
                    or meta.get('split')!='development' or meta.get('method') not in ('pre','post')
                    or meta.get('policy_sha256')!=policies[method]):
                raise ValueError('previous_feedback_identity_mismatch')
            if not execution_source_matches(meta.get('source_hashes'),expected_source_hashes):
                raise ValueError('previous_feedback_source_changed')
            metadata.append((method,seed,path,meta))
    for method,seed,path,meta in metadata:
        row=json.loads((path/'scored-record.json').read_text())
        if any(row.get(key)!=meta.get(key) for key in ('benchmark','seed','split','method','policy_sha256')):
            raise ValueError('previous_feedback_score_identity_mismatch')
        rows.append(dict(row,method=method))
        provenance.append(dict(method=method,seed=seed,source=str(path),
            started_sha256=hashlib.sha256((path/'started.json').read_bytes()).hexdigest(),
            score_sha256=hashlib.sha256((path/'scored-record.json').read_bytes()).hexdigest()))
    value=dict(schema=FEEDBACK_SCHEMA,split='development',benchmark=benchmark,round=round_number,
        source_hashes=expected_source_hashes,parent_policy=parent_policy,parent_policy_sha256=parent_hash,
        candidate_policy_sha256=policies['post'],proposal=checked['proposal'],rows=rows,selection=selection)
    cases=[dict(case_id=f'{benchmark}-{s}',benchmark=benchmark,seed=s) for s in SPLITS['development']]
    checked_previous_development_feedback(value,current_parent_hash,cases,expected_source_hashes,2)
    output=Path(output)
    immutable_json(output,value)
    immutable_json(output.with_name(output.stem+'-provenance.json'),dict(
        scope='complete_previous_development_round_only',records=provenance))
    return value


async def propose(parent_path,manifest_path,ledger,output,previous_development_feedback=None,
                  expected_source_hashes=None,proposal_round=1):
    output=Path(output);parent=json.loads(Path(parent_path).read_text());ph=policy_sha256(parent)
    Provider,request_tokens=provider_components()
    request=build_proposal_request(parent,manifest_path,ph,token_counter=request_tokens,
        previous_development_feedback=previous_development_feedback,
        expected_source_hashes=expected_source_hashes,proposal_round=proposal_round)
    request_hash=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    if (output/'identity.json').exists():
        identity=json.loads((output/'identity.json').read_text())
        if identity.get('request_sha256')!=request_hash or identity.get('parent_policy_sha256')!=ph:
            raise ValueError('cached_proposal_input_changed')
    elif output.exists() and any(output.iterdir()):
        raise ProposalPaused('existing_proposal_requires_audit_no_resampling')
    output.mkdir(parents=True,exist_ok=True)
    immutable_json(output/'identity.json',dict(request_sha256=request_hash,parent_policy_sha256=ph,
                                     max_proposals=1,split='development'))
    immutable_json(output/'public-request.json',request)
    ids=[x['case_id'] for x in json.loads(Path(manifest_path).read_text())['cases']]
    if (output/'candidate.json').exists():
        cached=json.loads((output/'candidate.json').read_text())
        checked=validate_and_apply_proposal(parent,cached['proposal'],ids,ph)
        if checked!=cached:raise ValueError('cached_candidate_changed')
        immutable_json(output/'policy.json',checked['candidate_policy'])
        return checked
    if (output/'rejection.json').exists():
        rejection=json.loads((output/'rejection.json').read_text())
        if rejection.get('kind')!='candidate_rejected':
            raise ProposalPaused('prior_proposal_requires_audit_no_resampling')
        return dict(rejected=True,adopted=False,parent_policy_sha256=ph,rejection=rejection)
    if (output/'attempt-started.json').exists():
        # A saved response can be deterministically parsed after a crash. A
        # missing response must never cause an uncertain request to be resent.
        if not (output/'response.json').exists():
            raise ProposalPaused('prior_proposal_requires_audit_no_resampling')
        response=json.loads((output/'response.json').read_text())
    else:
        ledger=Path(ledger);ledger.parent.mkdir(parents=True,exist_ok=True)
        # Same admission lock as full trajectories: a proposal cannot consume
        # the capacity already admitted to a running 480-call episode.
        with ledger.with_suffix('.admission.lock').open('a') as admission:
            fcntl.flock(admission,fcntl.LOCK_EX)
            # If a process died after its durable charge but before writing the
            # local start marker, that admission is still an uncertain attempt.
            # Do not hide it by charging/sampling again on restart.
            if ledger.exists():
                with ledger.with_suffix('.lock').open('a') as budget_lock:
                    fcntl.flock(budget_lock,fcntl.LOCK_SH)
                    entries=json.loads(ledger.read_text()).get('entries',[])
                if any(e.get('purpose')=='rule_proposal' and e.get('case_id')==str(output.resolve()) for e in entries):
                    raise ProposalPaused('charged_proposal_without_response_requires_audit')
            try:sequence=charge(ledger,'rule_proposal',str(output.resolve()))
            except LearningBudgetExhausted:
                raise ProposalPaused('learning_budget_exhausted_before_proposal') from None
            immutable_json(output/'attempt-started.json',dict(sequence=sequence,max_proposals=1))
            provider=None
            try:
                provider=Provider(output)
                raw=await provider.chat(**request)
                response=raw if isinstance(raw,dict) else asdict(raw)
                immutable_json(output/'response.json',response)
            except Exception as error:
                write(output/'transport-pause.json',dict(error_type=type(error).__name__,
                      code='proposal_transport_or_execution_requires_audit',resample=False))
                raise ProposalPaused('proposal_transport_or_execution_requires_audit') from None
            finally:
                if provider is not None:
                    try:await provider._client.close()
                    except Exception as error:
                        write(output/'provider-cleanup.json',dict(error_type=type(error).__name__,
                              response_preserved=(output/'response.json').exists(),resample=False))
    try:
        if not isinstance(response,dict):raise ValueError('proposal_response_schema_failure')
        calls=response.get('tool_calls') or []
        if (response.get('finish_reason') not in ('stop','tool_calls') or not isinstance(calls,list)
                or len(calls)!=1 or not isinstance(calls[0],dict)
                or calls[0].get('name')!='propose_memory_rule_edit'):
            raise ValueError('proposal_tool_protocol_failure')
        candidate=validate_and_apply_proposal(parent,calls[0]['arguments'],ids,ph)
    except (ValueError,TypeError,KeyError) as error:
        rejection=dict(kind='candidate_rejected',error_type=type(error).__name__,
             code=str(error) if isinstance(error,ValueError) else 'proposal_schema_failure',adopted=False)
        immutable_json(output/'rejection.json',rejection)
        return dict(rejected=True,adopted=False,parent_policy_sha256=ph,rejection=rejection)
    immutable_json(output/'candidate.json',candidate)
    immutable_json(output/'policy.json',candidate['candidate_policy'])
    return candidate

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    asyncio.run(propose(a.parent,a.manifest,a.ledger,a.output))
if __name__=='__main__':main()
