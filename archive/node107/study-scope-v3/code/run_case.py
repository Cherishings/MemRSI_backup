"""One real LIBERO episode, with public method wiring and immutable inputs."""
import argparse, asyncio, hashlib, json, os, sys, time, traceback
from pathlib import Path
from types import SimpleNamespace

def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_name(path.name+f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n'); tmp.replace(path)

def verify(root):
    m=json.loads((root/'registration.json').read_text())
    assert hashlib.sha256((root/'registration.json').read_bytes()).hexdigest()==(root/'registration.sha256').read_text().strip()
    for name, expected in m['frozen_files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('registered_input_changed:'+name)
    return m

def verify_job(root, registration, job):
    """Bind dispatch to the frozen phase, condition, policy and output identity."""
    root=Path(root)
    if job.get('gpu') not in registration['gpus']:
        raise RuntimeError('unregistered_gpu')
    phase=job.get('phase')
    if phase=='final':
        raw=(root/'final-registration.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=(root/'final-registration.sha256').read_text().strip():
            raise RuntimeError('final_registration_changed')
        final=json.loads(raw)
        if final['registration_sha256']!=(root/'registration.sha256').read_text().strip():
            raise RuntimeError('final_registration_parent_mismatch')
        if final['conditions']!=registration['test_conditions']:
            raise RuntimeError('final_conditions_changed')
        if job.get('arm') not in final['distinct_arms']:
            raise RuntimeError('unregistered_final_arm')
        allowed=final['conditions']
    elif phase in ('development/train','development/validation'):
        if job.get('arm')!='gu_parent':
            raise RuntimeError('development_parent_only')
        allowed=registration['training_conditions' if phase.endswith('/train') else 'validation_conditions']
    else:
        raise RuntimeError('unregistered_phase')
    fields=('condition_id','history','variant','init')
    if not any(all(job.get(k)==condition[k] for k in fields) for condition in allowed):
        raise RuntimeError('unregistered_condition')
    expected_output=root/phase/job['condition_id']/job['arm']
    if Path(job['output']).resolve()!=expected_output.resolve():
        raise RuntimeError('unregistered_output_path')
    policy=job.get('policy')
    expected=json.loads(Path(policy).read_text()) if policy else None
    if policy and hashlib.sha256(Path(policy).read_bytes()).hexdigest()!=job.get('policy_file_sha256'):
        raise RuntimeError('job_policy_changed')
    if phase=='final':
        canonical=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
        if canonical!=final['canonical_policy_hashes'][job['arm']]:
            raise RuntimeError('frozen_final_policy_changed')
    else:
        if policy is None or Path(policy).resolve()!=(root/'parent-policy.json').resolve():
            raise RuntimeError('development_parent_policy_changed')
        if job.get('policy_file_sha256')!=registration['frozen_files']['parent-policy.json']:
            raise RuntimeError('development_parent_hash_changed')
    if (job['arm']=='native')!=(expected is None):
        raise RuntimeError('native_policy_binding_changed')
    return expected

async def main(a):
    root=Path(a.root); m=verify(root); job=json.loads(Path(a.job).read_text())
    expected=verify_job(root,m,job)
    os.environ.update(PAOS_LIBERO_SOURCE=str(root/'source'), PAOS_CORE_ROOT=str(root/'paos-core'))
    sys.path[:0]=[str(root/'code'),str(root/'code/runtime'),str(root/'code/protocol')]
    import runtime_adapter
    runtime_adapter.configure(job['gpu'],20500+job['gpu'],str(root/'paos-core'))
    import feedback_workflow, twenty_agent, twenty_protocol, model_provider, planning, method
    feedback_workflow.plan=planning.bind_registered_plan(twenty_protocol.plan,m['all_histories'])
    policy=job['policy']
    twenty_agent.TwentyAgent=method.bind_agent_class(twenty_agent.TwentyAgent,job['arm'],expected)
    model_provider.CALL_LIMIT=m['call_limit_per_case']
    out=Path(job['output'])
    if out.exists(): raise RuntimeError('existing_case_no_automatic_replay')
    args=SimpleNamespace(output=str(out),orders=str(root/'orders.json'),port=20500+job['gpu'],
        init=job['init'],variant=job['variant'],history=job['history'],
        arm='native' if policy is None else 'memrsi',budget=str(root/'budget.json'),memory_policy=policy)
    result=await feedback_workflow.run(args)
    method_codes={'native_session_archival_failed','agent_call_budget_exhausted','guidance_review_protocol_failure',
        'guidance_protocol_failure','guidance_grounding_failure','advisor_protocol_failure','advisor_invalid_citation',
        'action_protocol_failure','persistent_memory_budget_exhausted','active_context_budget_exceeded','generation_output_limit'}
    result['registered_failure_class']='method_failure' if result.get('error_code') in method_codes else result['status']
    result.update(registered_arm=job['arm'],condition_id=job['condition_id'],phase=job['phase'],
        gpu=job['gpu'],registration_sha256=(root/'registration.sha256').read_text().strip(),attempt=1,
        policy_file_sha256=job.get('policy_file_sha256'),finished_at=time.time())
    write(out/'result.json',result)
    if result['registered_failure_class']=='infrastructure_failure':return 2
    return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--job',required=True)
    a=p.parse_args()
    try: sys.exit(asyncio.run(main(a)))
    except Exception as e:
        write(Path(a.job).with_suffix('.failure.json'),{'type':type(e).__name__,'error':str(e)[:300], 'automatic_retry':False})
        traceback.print_exc();sys.exit(2)
