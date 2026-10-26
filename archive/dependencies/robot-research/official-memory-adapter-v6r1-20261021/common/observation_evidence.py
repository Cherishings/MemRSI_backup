"""Bounded public visual notes captured in the existing action-model call.

This shared adapter does not infer facts, assess completion, retain a special
world state, or change native archive rules. It only validates and labels what
the acting model reported from its current observation. Both experimental arms
receive the same surface and the same limits. The tool response survives in
ordinary session history, unlike a historical image's ``[image]`` placeholder.
"""
import json


FIELDS = ("visible_facts", "progress_uncertainty", "reference_to_preserve")
MAX_FIELD_CHARS = 256
MAX_OBSERVATION_CHARS = 768

OBSERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "visible_facts": {
            "type": "string", "maxLength": MAX_FIELD_CHARS,
            "description": "Brief current visual observations, not inferred task success. Empty if unknown.",
        },
        "progress_uncertainty": {
            "type": "string", "maxLength": MAX_FIELD_CHARS,
            "description": "What task progress the current observation does or does not establish. Empty is allowed.",
        },
        "reference_to_preserve": {
            "type": "string", "maxLength": MAX_FIELD_CHARS,
            "description": "Any task-relevant current visual detail that may be useful later. Empty if none.",
        },
    },
    "required": list(FIELDS),
    "additionalProperties": False,
}


def validate_observation(value):
    """Return a detached, canonically ordered note; never interpret its claims."""
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ValueError("observation_fields")
    if any(not isinstance(value[key], str) for key in FIELDS):
        raise ValueError("observation_field_type")
    if any(len(value[key]) > MAX_FIELD_CHARS for key in FIELDS):
        raise ValueError("observation_field_capacity")
    if sum(len(value[key]) for key in FIELDS) > MAX_OBSERVATION_CHARS:
        raise ValueError("observation_total_capacity")
    return {key: value[key] for key in FIELDS}


def render_observation(event_id, value):
    """Render an explicitly unverified pre-action note for the common tool reply.

The event ID links a note to the public observation that the actor saw. It is
not a private evaluator ID. In particular, a note saying "completed" remains
the model's assertion; this adapter neither verifies it nor changes any task
status. Notes are not merged or privileged over later observations by code.
"""
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        raise ValueError("observation_event_id")
    observation = validate_observation(value)
    record = {
        "event": event_id,
        "public_observation_ref": f"Event {event_id}",
        "source": "actor_generated_from_current_public_observation",
        "timing": "before_requested_action_execution",
        "verified_by_environment": False,
        "observation": observation,
    }
    return (
        "Public observation note: actor-generated, unverified pre-action claims. "
        "This note is not an execution receipt or confirmation of task success.\n"
        + json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
