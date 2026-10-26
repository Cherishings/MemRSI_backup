"""Common random numbers for physical comparisons; independent of agent/server history."""
import hashlib
import json
import numpy as np

BASE_SEED = 20261009

def sampling_seed(base, suite, task_id, initial, attempt, chunk):
    key = [int(base), str(suite), int(task_id), int(initial), int(attempt), int(chunk)]
    return int.from_bytes(hashlib.sha256(json.dumps(key).encode()).digest()[:4], 'little')

def array_hash(value):
    a = np.ascontiguousarray(value)
    return hashlib.sha256(str(a.dtype).encode()+str(a.shape).encode()+a.tobytes()).hexdigest()

def query_hash(query):
    parts = {}
    for k, v in sorted(query.items()):
        parts[k] = array_hash(v) if isinstance(v, np.ndarray) else v
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

class PairedPolicy:
    def __init__(self, policy, shape):
        self.policy = policy
        self.shape = tuple(shape)

    def infer(self, obs):
        obs = dict(obs)
        seed = obs.pop('_paired_sampling_seed')
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('invalid_sampling_seed')
        noise = np.random.Generator(np.random.PCG64(seed)).standard_normal(self.shape).astype(np.float32)
        inputs_hash = query_hash(obs)
        result = self.policy.infer(obs, noise=noise)
        result['paired_sampling'] = dict(seed=seed, noise_sha256=array_hash(noise),
                                        input_sha256=inputs_hash, actions_sha256=array_hash(result['actions']))
        return result
