"""Shared frozen Mem-0 execution module only; no Mem-0 planner or expert replay."""
from pathlib import Path
import hashlib
import json
import sys
from types import MethodType


class ExecutionLifecycle:
    """Planner-free lifecycle for the upstream execution methods.

    The reference is Mem_0/deploy_policy.py, not the separate XPolicyLab Model
    wrapper. In particular its internal prediction clock advances by the whole
    configured macro strip when a learned boundary interrupts a strip. Physical
    steps are counted separately and never inflated in benchmark scoring.
    """

    def __init__(self, agent, action_prefix=8, threshold=2):
        self.agent = agent
        self.action_prefix = action_prefix
        self.threshold = threshold
        self.instruction = None
        self.pending_steps = 0
        self.strip_size = 0
        self.boundary_ready = False
        self.executed_steps = 0
        self.observation_updates = 0
        self.semantic_resets = 0

    def _end_strip(self):
        if self.strip_size:
            self.agent.iter += self.strip_size
        self.pending_steps = 0
        self.strip_size = 0

    def begin(self, instruction, new_subtask=False):
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
            raise ValueError('nonempty bounded actor instruction required')
        changed = self.instruction is not None and instruction != self.instruction
        if changed and not (self.boundary_ready or new_subtask):
            raise ValueError('instruction_change_requires_semantic_boundary')
        if self.pending_steps and not (self.boundary_ready or new_subtask):
            raise ValueError('executed_step_observations_required_before_next_prediction')
        # A new semantic command, including a repeated command after a learned
        # end signal, follows the upstream subtask reset. Ordinary polling with
        # identical language never resets memory.
        if self.instruction is not None and (self.boundary_ready or new_subtask):
            self._end_strip()
            self.agent.executor.memory_bank.reset()
            self.agent.end_signal_count = 0
            self.agent.action_count = 0
            self.agent.stage += 1
            self.boundary_ready = False
            self.semantic_resets += 1
        self.instruction = instruction
        self.agent.instruction = instruction

    def predict(self, payload, instruction, new_subtask=False):
        import numpy as np
        self.begin(instruction, new_subtask)
        if self.agent.action_count == 0:
            # Exactly once at the beginning of an episode/subtask; subsequent
            # predictions use the cache from the actual preceding env.step.
            self.agent.update_obs(payload)
            self.observation_updates += 1
        result = self.agent.get_action()
        if result is None:
            raise RuntimeError('upstream_action_cache_empty')
        predicted = np.asarray(result['normalized_actions'])
        if predicted.shape not in ((1, 30, 16), (30, 16)) or not np.isfinite(predicted).all():
            raise ValueError('invalid frozen executor action chunk')
        self.agent.accumulate_actions_chunk(predicted)
        actions = self.agent.get_smoothed_actions(self.agent.iter, self.action_prefix)
        if actions.shape != (self.action_prefix, 16) or not np.isfinite(actions).all():
            raise ValueError('invalid upstream smoothed action strip')
        self.pending_steps = len(actions)
        self.strip_size = len(actions)
        return actions

    def observe_step(self, payload):
        if self.pending_steps <= 0:
            raise ValueError('observation_without_pending_executed_action')
        self.agent.update_obs(payload)
        self.observation_updates += 1
        self.executed_steps += 1
        self.pending_steps -= 1
        self.boundary_ready = bool(self.agent.end_signal_count >= self.threshold)
        if self.boundary_ready or self.pending_steps == 0:
            self._end_strip()
        return dict(subtask_end=self.boundary_ready, boundary_ready=self.boundary_ready,
                    signal_kind='learned_prediction_not_verified_success',
                    end_signal_count=int(self.agent.end_signal_count),
                    executed_steps=self.executed_steps,
                    pending_steps=self.pending_steps,
                    observation_updates=self.observation_updates,
                    semantic_resets=self.semantic_resets)


class _ExecutionState:
    """Explicit state used by the four unchanged upstream methods, no planner."""

    def __init__(self, executor, official_agent, action_prefix):
        self.executor = executor
        self.episode_id = 0
        self.is_init = 0
        self.action_horizon = action_prefix
        self.action_strip = action_prefix
        self.threshold = 2
        self._last_fused = None
        self._last_original = None
        self._last_state = None
        self._time_action_history = {}
        self.iter = self.stage = self.end_signal_count = self.action_count = 0
        self.instruction = ''
        for name in ('update_obs', 'get_action', 'accumulate_actions_chunk', 'get_smoothed_actions'):
            setattr(self, name, MethodType(getattr(official_agent, name), self))

ROOT = Path('/data/stormlab/xi/robot')
UPSTREAM = ROOT / 'memory-bench-prep/XPolicyLab-fa431ecd/policy/Mem_0/Mem_0'
ARTIFACTS = ROOT / 'models/official-memory-rmbench-20261017'
CHECKPOINT_SHA256 = 'b9e8fc2a8fecf3635519d12da12911c7193507b714fdd2c26bca14588d60786a'


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def env14_to_model16(state):
    import numpy as np
    state = np.asarray(state, dtype=np.float32)
    if state.shape != (14,) or not np.isfinite(state).all():
        raise ValueError('expected finite dual-arm native 14-D joint/gripper state')
    result = np.zeros(16, dtype=np.float32)
    result[:6] = state[:6]
    result[7:13] = state[7:13]
    result[14], result[15] = state[6], state[13]
    return result


def model16_to_env14(action):
    import numpy as np
    action = np.asarray(action, dtype=np.float32)
    if action.shape != (16,) or not np.isfinite(action).all():
        raise ValueError('expected finite model 16-D action')
    return np.concatenate([action[:6], action[14:15], action[7:13], action[15:16]])


class FrozenRMBenchExecutor:
    def __init__(self, device='cuda:0', checkpoint=None, stats_path=None, backbone=None):
        checkpoint = Path(checkpoint or ARTIFACTS / 'mn/checkpoints/cover_blocks/final_step30000.pt')
        stats_path = Path(stats_path or ARTIFACTS / 'mn/norm_stats/cover_blocks/norm_stats.json')
        backbone = Path(backbone or ARTIFACTS / 'qwen2b')
        if not checkpoint.is_file() or not stats_path.is_file() or not (backbone / 'model.safetensors').is_file():
            raise FileNotFoundError('frozen executor checkpoint, paired stats, and complete backbone must exist; random weights forbidden')
        if file_sha256(checkpoint) != CHECKPOINT_SHA256:
            raise ValueError('checkpoint SHA256 differs from pinned public artifact')
        sys.path.insert(0, str(UPSTREAM))
        import numpy as np
        import torch
        from omegaconf import OmegaConf
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        from source.models.execution_module import memorymatters_executor as executor_module
        from source.models.execution_module.qwen3_vl_model.qwen3_vl_encapsulation import Qwen3VL_Encapsulation
        from scripts.tools_for_deploy.normlization import load_stats, normalize_arms, denormalize_arms

        class SdpaQwen(Qwen3VL_Encapsulation):
            """Same learned architecture and feature extraction with PyTorch SDPA backend."""
            def __init__(self, model_path, device=None, **kwargs):
                torch.nn.Module.__init__(self)
                target = device if device is not None else torch.device('cuda:0')
                self.model = Qwen3VLForConditionalGeneration.from_pretrained(
                    model_path, dtype=torch.bfloat16, attn_implementation='sdpa',
                    local_files_only=True).to(target)
                self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
                self.processor.tokenizer.padding_side = 'right'
                self.hidden_size = self.model.config.vision_config.out_hidden_size
                self.vision_start_token_id = self.processor.vision_start_token_id
                self.vision_end_token_id = self.processor.vision_end_token_id
                self.im_end_token_id = self.processor.tokenizer.convert_tokens_to_ids('<|im_end|>')
                self.image_token_id = self.processor.image_token_id

        cfg = OmegaConf.load(UPSTREAM.parent / 'deploy.yml')
        cfg.execution_module.qwen_vl.model_path = str(backbone)
        original_factory = executor_module.Qwen3VL_Encapsulation
        executor_module.Qwen3VL_Encapsulation = SdpaQwen
        try:
            self.executor = executor_module.MemoryMattersExecutor(cfg, device=torch.device(device)).to(device)
        finally:
            executor_module.Qwen3VL_Encapsulation = original_factory
        # The pinned checkpoint stores a NumPy float64 training metric alongside
        # model tensors. Permit only these data constructors; keep restricted loading.
        with torch.serialization.safe_globals([
                np.core.multiarray.scalar, np.dtype, type(np.dtype(np.float64))]):
            payload = torch.load(checkpoint, map_location='cpu', weights_only=True)
        state_dict = payload['model_state_dict']
        self.executor.load_state_dict(state_dict, strict=True)
        del payload, state_dict
        self.executor.eval().requires_grad_(False)
        self.stats = load_stats(str(stats_path))
        for key in ['state_min', 'state_max', 'action_min', 'action_max']:
            if self.stats[key] is None:
                raise ValueError('matching min-max normalization statistics required')
        self.normalize_arms, self.denormalize_arms = normalize_arms, denormalize_arms
        # Eight is a supported configurable cover_blocks example, not the
        # universal upstream default (which is thirty). The learned model still
        # predicts thirty steps; both comparison arms use the same eight strip.
        self.action_prefix = 8
        from source.agent.memorymatters_agent import MemoryMattersAgent
        self._official_agent = MemoryMattersAgent
        official_source = UPSTREAM / 'source/agent/memorymatters_agent.py'
        self.identity = {'controller': 'frozen_Mem0_cover_blocks_upstream_execution_lifecycle_v5',
                         'checkpoint_sha256': CHECKPOINT_SHA256,
                         'stats_sha256': file_sha256(stats_path), 'attention_backend': 'sdpa',
                         'action_prefix': self.action_prefix, 'learned_memory_bank': 'identical frozen lower-level history processing in both arms',
                         'planner': 'external PAOS or frozen MemRSI; Mem0 planner never constructed',
                         'upstream_agent_sha256': file_sha256(official_source),
                         'reused_upstream_methods': ['update_obs', 'get_action', 'accumulate_actions_chunk', 'get_smoothed_actions'],
                         'lifecycle_reference': 'Mem_0/deploy_policy.py',
                         'memory_update_frequency': 'initial_observation_and_each_executed_step',
                         'semantic_end_threshold': 2,
                         'semantic_end_is_learned_prediction': True,
                         'training_enabled': False}
        self.reset(0)

    def reset(self, episode_seed):
        import random
        import numpy as np
        import torch
        random.seed(episode_seed)
        np.random.seed(episode_seed)
        torch.manual_seed(episode_seed)
        torch.cuda.manual_seed_all(episode_seed)
        self.executor.memory_bank.reset()
        self.episode_id = 0
        agent = _ExecutionState(self.executor, self._official_agent, self.action_prefix)
        self.lifecycle = ExecutionLifecycle(agent, self.action_prefix)

    def _observation_payload(self, rgb_head, joint_state, instruction):
        import numpy as np
        from PIL import Image
        rgb = np.asarray(rgb_head)
        if rgb.ndim != 3 or rgb.shape[-1] != 3 or rgb.dtype != np.uint8:
            raise ValueError('public head-camera RGB uint8 observation required')
        model_state = env14_to_model16(joint_state)
        normalized = self.normalize_arms(model_state, None, None,
                                         self.stats['state_min'], self.stats['state_max'], arm_dims=14)
        return {'image': Image.fromarray(rgb), 'state': normalized.reshape(1, -1),
                'instruction': instruction}

    def predict(self, rgb_head, joint_state, instruction, new_subtask=False):
        import numpy as np
        if not isinstance(new_subtask, bool):
            raise ValueError('new_subtask_requires_boolean')
        payload = self._observation_payload(rgb_head, joint_state, instruction)
        predicted = self.lifecycle.predict(payload, instruction, new_subtask)
        actions = []
        for step in predicted:
            denormalized = self.denormalize_arms(step, None, None,
                                                 self.stats['action_min'], self.stats['action_max'], arm_dims=14)
            actions.append(model16_to_env14(denormalized))
        # The boundary is assessed after actual execution, by observe_step.
        return {'actions': np.asarray(actions, dtype=np.float32),
                'subtask_end': self.lifecycle.boundary_ready,
                'boundary_ready': self.lifecycle.boundary_ready,
                'requires_observe_after_each_action': True,
                'controller': self.identity}

    def observe_step(self, rgb_head, joint_state):
        if self.lifecycle.instruction is None:
            raise ValueError('observation_before_first_instruction')
        payload = self._observation_payload(rgb_head, joint_state, self.lifecycle.instruction)
        return self.lifecycle.observe_step(payload)
