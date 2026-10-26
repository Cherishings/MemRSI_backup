"""Bounded physical OSC handoff, using only observed EEF pose and env.step.

The caller owns the simulator and the sole action callback. This helper never
resets an environment, changes simulation state, or marks a business event done.
"""
from __future__ import annotations

import numpy as np


def _bounds(controller):
    if not getattr(controller, 'use_delta', False):
        raise ValueError('Physical handoff requires use_delta=True OSC')
    if getattr(controller, 'impedance_mode', 'fixed') != 'fixed':
        raise ValueError('Physical handoff requires fixed-impedance OSC')
    arrays = [np.broadcast_to(np.asarray(getattr(controller, name), dtype=float), (6,)).copy()
              for name in ('input_min', 'input_max', 'output_min', 'output_max')]
    low, high, out_low, out_high = arrays
    if (not all(np.isfinite(x).all() for x in arrays) or np.any(high <= low)
            or np.any(out_high <= out_low) or np.any(out_low > 0) or np.any(out_high < 0)):
        raise ValueError('Invalid OSC action scaling bounds')
    return arrays


def read_pose(controller):
    controller.update(force=True)
    position = np.asarray(controller.ee_pos, dtype=float).copy()
    rotation = np.asarray(controller.ee_ori_mat, dtype=float).copy()
    if (position.shape != (3,) or rotation.shape != (3, 3)
            or not np.isfinite(position).all() or not np.isfinite(rotation).all()
            or not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-4)
            or not np.isclose(np.linalg.det(rotation), 1, atol=1e-4)):
        raise ValueError('Invalid observed EEF pose')
    return position, rotation


def capture_home(controller):
    """Capture the pose after the caller's sole initialization and settling."""
    position, rotation = read_pose(controller)
    bounds = _bounds(controller)
    return {'position': position.tolist(), 'orientation': rotation.tolist(),
            'controller_scale': dict(zip(('input_min', 'input_max', 'output_min', 'output_max'),
                                         [x.tolist() for x in bounds]))}


def rotation_vector(rotation):
    """SO(3) logarithm, including the near-pi case, in world coordinates."""
    rotation = np.asarray(rotation, dtype=float)
    angle = float(np.arccos(np.clip((np.trace(rotation) - 1) / 2, -1, 1)))
    skew = np.array([rotation[2, 1] - rotation[1, 2],
                     rotation[0, 2] - rotation[2, 0],
                     rotation[1, 0] - rotation[0, 1]])
    if angle < 1e-7:
        return 0.5 * skew
    if np.pi - angle < 1e-5:
        _, vectors = np.linalg.eigh((rotation + rotation.T + 2 * np.eye(3)) / 4)
        axis = vectors[:, -1]
        if np.linalg.norm(skew) > 1e-10 and np.dot(axis, skew) < 0:
            axis = -axis
        return angle * axis
    return angle * skew / (2 * np.sin(angle))


def _limit_norm(vector, limit):
    norm = float(np.linalg.norm(vector))
    return vector if norm <= limit else vector * (limit / norm)


def normalized_action(controller, position_delta, rotation_delta):
    """Invert the controller's actual scale_action map, then clip its inputs."""
    low, high, out_low, out_high = _bounds(controller)
    scale = np.abs(out_high - out_low) / np.abs(high - low)
    delta = np.r_[position_delta, rotation_delta]
    normalized = (delta - (out_high + out_low) / 2) / scale + (high + low) / 2
    # -1 is the verified opening direction of this LIBERO gripper.
    return np.r_[np.clip(normalized, low, high), -1.0]


def run_handoff(controller, home, step_action, step_budget, max_handoff_steps=180,
                lift_clearance=0.08, position_step=0.015, rotation_step=0.1,
                position_tolerance=0.01, rotation_tolerance=0.08):
    """Open, lift vertically, return at height, and descend via real actions.

    step_action(action7, phase) must call the real environment once and record
    that action/frame. step_budget is the remaining *physical* budget, including
    this handoff. No business predicate is accepted by this helper.
    """
    if type(step_budget) is not int or step_budget < 0 or max_handoff_steps <= 0:
        raise ValueError('Handoff budgets must be nonnegative physical step counts')
    if min(lift_clearance, position_step, rotation_step, position_tolerance, rotation_tolerance) <= 0:
        raise ValueError('Handoff control tolerances and step sizes must be positive')
    start_position, start_rotation = read_pose(controller)
    home_position = np.asarray(home['position'], dtype=float)
    home_rotation = np.asarray(home['orientation'], dtype=float)
    if home_position.shape != (3,) or home_rotation.shape != (3, 3):
        raise ValueError('Invalid saved home pose')
    limit = min(step_budget, max_handoff_steps)
    report = {'success': False, 'failure_reason': None, 'steps': 0, 'step_budget': step_budget,
              'handoff_limit': max_handoff_steps, 'phases': [], 'setpoint_initialized': False,
              'setpoint_initialization': None, 'counts_as_business_event': False}

    def errors(position, rotation):
        observed_position, observed_rotation = read_pose(controller)
        return (position - observed_position,
                rotation_vector(rotation @ observed_rotation.T))

    def finalize(reason=None):
        pos_error, rot_error = errors(home_position, home_rotation)
        report.update(success=reason is None, failure_reason=reason,
                      final_pose_error={'position_m': float(np.linalg.norm(pos_error)),
                                        'orientation_rad': float(np.linalg.norm(rot_error))})
        return report

    if limit == 0:
        return finalize('physical_step_budget_exhausted')

    # OSC ignores a zero rotation delta when updating goal_ori. Clear only the
    # stale control setpoint, through its public API, to the observed pose. This
    # changes no simulator qpos/qvel and consumes no fictitious physics step.
    neutral = normalized_action(controller, np.zeros(3), np.zeros(3))[:6]
    controller.set_goal(neutral, set_pos=start_position.copy(), set_ori=start_rotation.copy())
    report['setpoint_initialized'] = True
    report['setpoint_initialization'] = {
        'method': 'controller.set_goal', 'position': start_position.tolist(),
        'orientation': start_rotation.tolist(), 'simulation_state_modified': False}

    height = max(float(home_position[2]), float(start_position[2]) + lift_clearance)
    phases = [
        ('open_gripper', start_position, start_rotation, 5),
        ('lift', np.array([start_position[0], start_position[1], height]), start_rotation, 3),
        ('return_high', np.array([home_position[0], home_position[1], height]), home_rotation, 3),
        ('descend', home_position, home_rotation, 5),
    ]
    for phase, position, rotation, required_stable in phases:
        record = {'phase': phase, 'target_position': position.tolist(),
                  'target_orientation': rotation.tolist(), 'steps': 0, 'success': False}
        report['phases'].append(record)
        stable = 0
        while report['steps'] < limit:
            pos_delta, rot_delta = errors(position, rotation)
            action = normalized_action(controller, _limit_norm(pos_delta, position_step),
                                       _limit_norm(rot_delta, rotation_step))
            step_action(action, phase)
            report['steps'] += 1
            record['steps'] += 1
            pos_error, rot_error = errors(position, rotation)
            record['position_error_m'] = float(np.linalg.norm(pos_error))
            record['orientation_error_rad'] = float(np.linalg.norm(rot_error))
            within = (record['position_error_m'] <= position_tolerance
                      and record['orientation_error_rad'] <= rotation_tolerance)
            stable = stable + 1 if within else 0
            if stable >= required_stable:
                record['success'] = True
                break
        if not record['success']:
            reason = ('physical_step_budget_exhausted' if step_budget <= max_handoff_steps
                      else 'handoff_step_budget_exhausted')
            return finalize(reason)
    return finalize()


def handoff_transition_success(skill_transition, handoff, goal_satisfied_after):
    """The caller evaluates native predicates after all real handoff motion."""
    return bool(skill_transition and handoff.get('success') and goal_satisfied_after)
