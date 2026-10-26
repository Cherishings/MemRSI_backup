"""Bind new episode workers to the exact reviewed shared visual adapter."""
import hashlib
import json
from pathlib import Path

REQUIRED = {'visual_actor.py', 'visual_accounting.py', 'visual_budget.py'}
CORE = Path('/data/stormlab/xi/paos/worktrees/memrsi-bounded-v2_2')
PAOS = Path('/data/stormlab/xi/PhyAgentOS-core/PhyAgentOS')
REQUIRED_RUNTIME = {str(CORE / name) for name in (
    'twenty_agent.py', 'agent_adapter.py', 'model_provider.py', 'memory_ops.py',
    'memory_policy.py', 'memory_budget.py', 'token_accounting.py')}
REQUIRED_RUNTIME |= {str(PAOS / name) for name in (
    'agent/loop.py', 'agent/memory.py', 'agent/context.py',
    'agent/context_budget.py', 'session/manager.py')}


def checked(common):
    common = Path(common)
    proof = json.loads((common / 'visual-validation-ready.json').read_text())
    if proof.get('status') != 'passed' or proof.get('version') != 'visual-v2':
        raise RuntimeError('visual_adapter_validation_missing')
    if not REQUIRED <= set(proof.get('code_hashes', {})):
        raise RuntimeError('visual_adapter_hash_set_incomplete')
    for name in REQUIRED:
        if hashlib.sha256((common / name).read_bytes()).hexdigest() != proof['code_hashes'][name]:
            raise RuntimeError('visual_validated_code_changed')
    if proof.get('pre_guidance_archive_reserve_units') != 2048 or proof.get('active_input_units') != 12288:
        raise RuntimeError('visual_resource_protocol_changed')
    if not REQUIRED_RUNTIME <= set(proof.get('runtime_source_sha256', {})):
        raise RuntimeError('visual_runtime_hash_set_incomplete')
    for path, expected in proof['runtime_source_sha256'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('visual_native_runtime_changed')
    return proof
