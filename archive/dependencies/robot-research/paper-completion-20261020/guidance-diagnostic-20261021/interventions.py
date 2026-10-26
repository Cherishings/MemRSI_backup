"""Registered diagnostic interventions; no task answers or action changes."""
import copy
import hashlib
import json
from cap10_ops import MemoryOps as Cap10Ops

ARMS = ('cap5_control', 'cap10', 'cadence2_full', 'cadence2_no_short')

def agent_class(base, arm):
    if arm not in ARMS:
        raise ValueError('unregistered_arm')
    class Diagnostic(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.requested_boundaries = 0
            self.actual_boundaries = 0
            if self.ops is None:
                raise RuntimeError('guidance_required')
            if arm == 'cap10':
                policy = copy.deepcopy(self.ops.policy)
                spec = json.loads(policy['guidance'])
                old = 'Select up to five evidence fragment IDs'
                if spec['procedure'].count(old) != 1:
                    raise RuntimeError('unexpected_frozen_guidance_instruction')
                spec['procedure'] = spec['procedure'].replace(old, 'Select up to ten evidence fragment IDs')
                policy['guidance'] = json.dumps(spec, ensure_ascii=False)
                self.ops = Cap10Ops(self.ops.provider, self.ops.workspace, self.ops.output,
                                    policy, self.ops.action_contract)
            original = self.ops.guide
            async def guide(short, current):
                selected_short = [] if arm == 'cadence2_no_short' else short
                self.provider._append('diagnostic-exposure.jsonl', {
                    'arm': arm, 'native_short_messages': len(short),
                    'guidance_short_messages': len(selected_short),
                    'native_short_sha256': hashlib.sha256(json.dumps(short, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                    'actor_history_untouched': True,
                    'requested_boundaries': self.requested_boundaries,
                    'actual_explicit_boundaries': self.actual_boundaries})
                return await original(selected_short, current)
            self.ops.guide = guide
            self._write('diagnostic-intervention.json', {
                'arm': arm, 'selection_cap': 10 if arm == 'cap10' else 5,
                'explicit_boundary_interval': 2 if arm.startswith('cadence2') else 1,
                'automatic_native_token_consolidation_unchanged': True,
                'actor_history_untouched_by_guidance_intervention': True,
                'effective_guidance_policy': self.ops.policy,
                'frozen_actor_and_update_policy_unchanged': True,
                'engine_session_switches_counts_requested_boundaries': True})

        async def rollover(self):
            self.requested_boundaries += 1
            execute = not arm.startswith('cadence2') or self.requested_boundaries % 2 == 0
            self.provider._append('diagnostic-boundaries.jsonl', {
                'requested_index': self.requested_boundaries, 'execute_native_new': execute,
                'reason': 'registered_interval', 'arm': arm})
            if execute:
                await super().rollover()
                self.actual_boundaries += 1
    return Diagnostic
