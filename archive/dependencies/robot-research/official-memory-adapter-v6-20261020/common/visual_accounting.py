"""Shared resource units for the NEW visual benchmark adapter, not vendor billing.

The old text-only experiments are unchanged. Base64 is transport encoding, not
text context. Every image costs 1024 declared resource units in both arms.
"""
import copy
import hashlib
import json

IMAGE_UNITS = 1024
MAX_CAMERAS = 3
MAX_IMAGE_EDGE = 256
ALLOWED_PROPRIO = frozenset({
    'joint_pos', 'joint_vel', 'eef_pos', 'eef_quat', 'gripper_qpos',
    'gripper_qvel', 'base_pos', 'base_quat', 'joint_action', 'endpose',
})


def accounting_messages(messages):
    normalized = copy.deepcopy(messages)
    count = 0
    for message in normalized:
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for index, part in enumerate(content):
            if part.get('type') != 'image_url':
                continue
            image = part.get('image_url')
            url = image.get('url') if isinstance(image, dict) else image
            if not isinstance(url, str) or not url.startswith('data:image/'):
                raise ValueError('only_local_camera_images_allowed')
            count += 1
            content[index] = {'type': 'text', 'text': '[camera image]'}
    if count > MAX_CAMERAS:
        raise ValueError('camera_budget_exceeded')
    return normalized, count * IMAGE_UNITS, count


def public_proprio(values):
    """Reject unknown data instead of inadvertently carrying task oracle fields."""
    if not isinstance(values, dict) or set(values) - ALLOWED_PROPRIO:
        raise ValueError('non_public_proprio_field')
    def numeric(v):
        if hasattr(v, 'tolist'):
            v = v.tolist()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        if isinstance(v, (list, tuple)):
            return [numeric(x) for x in v]
        raise ValueError('proprio_must_be_numeric')
    result = {k: numeric(v) for k, v in values.items()}
    json.dumps(result, allow_nan=False)
    return result


def image_evidence(paths):
    return [{'camera': i, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for i, p in enumerate(paths)]
