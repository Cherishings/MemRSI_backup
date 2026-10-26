"""Non-secret version fingerprints and shared execution seeding."""
import hashlib,json,random
from pathlib import Path

def code_hashes(root=None):
    root=Path(root or __file__).resolve()
    if root.is_file():root=root.parent
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir()) if p.suffix in ('.py','.json')}

def seed_all(seed):
    import numpy as np,torch
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)
    return dict(python=seed,numpy=seed,torch=seed,cuda=seed)

def initial_evidence(env,public,seed):
    import base64,numpy as np
    return dict(seed=seed,execution_seed=seed,public_instruction=public['instruction'],public_rgb_sha256=[hashlib.sha256(base64.b64decode(x['rgb_base64'])).hexdigest() for x in public['cameras']],simulator_state_sha256=hashlib.sha256(np.asarray(env.sim.get_state().flatten()).tobytes()).hexdigest(),evaluator_only=True)
