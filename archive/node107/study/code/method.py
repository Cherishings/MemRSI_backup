"""Bounded, policy-driven memory advice for LIBERO and matched controls.

No evaluator imports, score lookup, physical action execution, persistent task
ledger, or action veto. The native actor remains responsible for every action.
The initial G design and r2 U are manual parent rules, not an RSI result.
"""
import copy
import hashlib
import json
from pathlib import Path

ARMS = ("native", "g_only", "u_only", "gu_parent", "gu_learned", "think_u",
        "rsi_g_only", "rsi_u_only")
MODEL = "gpt-5.6-luna"
GUIDANCE_PARENT = (
    "Advise the acting agent from the supplied public memory, current conversation, request and execution API. "
    "First distinguish an explicit current work order from a request to resume earlier work. "
    "For resumed work, combine the originating request and its original ordering with later revisions or cancellations; "
    "resolve relative references against the order they actually refer to, not the newest incidental mention. "
    "Combine each submitted action with its correlated actual receipt before inferring completion. "
    "An assistant commitment, repeated observation, or tool capability alone does not establish requested or completed work. "
    "Recent unrelated receipts must not displace an older still-governing request or revision. "
    "Explain one supported next-action recommendation, citing the evidence IDs that jointly support it. "
    "Treat summaries as fallible; preserve conflicts and abstain when the necessary evidence is missing or ambiguous. "
    "Never invent a prerequisite, fact, completion, instruction or tool. You cannot execute or forbid an action. "
    "The actor independently verifies the evidence and may reject the recommendation."
)
DELIBERATION = (
    "Take one additional deliberation pass on the supplied public memory, conversation, current request and execution API. "
    "Recommend one next action, cite its supporting evidence IDs and state uncertainty. "
    "You may abstain. Do not invent evidence or execute an action. The actor independently decides and may reject your advice."
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != {"schema", "guidance", "update"} or value["schema"] != 1:
        raise ValueError("policy_schema")
    if any(not isinstance(value[k], str) or len(value[k]) > 1800 for k in ("guidance", "update")):
        raise ValueError("policy_length")
    return copy.deepcopy(value)


def guidance_rule(procedure):
    if not isinstance(procedure, str) or not procedure.strip() or len(procedure) > 1600:
        raise ValueError("guidance_procedure_length")
    return json.dumps({"kind": "procedure_guidance_v2", "procedure": procedure}, sort_keys=True)


def guidance_procedure(policy):
    spec = json.loads(validate_policy(policy)["guidance"])
    if not isinstance(spec, dict) or spec.get("kind") != "procedure_guidance_v2":
        raise ValueError("guidance_procedure_schema")
    procedure = spec.get("procedure")
    guidance_rule(procedure)
    return procedure


def policy_for(parent, learned, arm):
    """Final-method ablations plus independent learned-rule swap comparisons.

    rsi_g_only/rsi_u_only enable BOTH operators; only the named operator is
    replaced by its learned version. They are learning-component controls.
    Pass learned=None while registering manual-parent development.
    """
    if arm not in ARMS:
        raise ValueError("unregistered_arm")
    if arm == "native":
        return None
    parent = validate_policy(parent)
    learned = validate_policy(parent if learned is None else learned)
    if any(not p[k] for p in (parent, learned) for k in ("guidance", "update")):
        raise ValueError("complete_parent_and_learned_required")
    result = copy.deepcopy(parent if arm in ("gu_parent", "rsi_g_only", "rsi_u_only") else learned)
    if arm == "g_only":
        result["update"] = ""
    elif arm == "u_only":
        result["guidance"] = ""
    elif arm == "think_u":
        result["guidance"] = guidance_rule(DELIBERATION)
    elif arm == "rsi_g_only":
        result["guidance"] = learned["guidance"]
    elif arm == "rsi_u_only":
        result["update"] = learned["update"]
    return validate_policy(result)


def public_messages(messages):
    """Allow only public native conversation fields; never inspect scoring data."""
    allowed = ("role", "content", "tool_calls", "tool_call_id", "name")
    return [{k: copy.deepcopy(m[k]) for k in allowed if k in m} for m in messages]


def public_payload(memory, history, messages, current, action_contract):
    if not isinstance(action_contract, str) or not action_contract.strip():
        raise ValueError("missing_public_action_contract")
    evidence = {"memory": memory, "history": history, "current": current}
    evidence.update({f"short:{i}": m for i, m in enumerate(public_messages(messages))})
    return {"execution_api": action_contract, "evidence": evidence}


def advice_tools(evidence):
    schema = {"type": "object", "properties": {
        "recommendation": {"type": "string", "maxLength": 1200,
                           "description": "Nonbinding next-action recommendation; empty means abstain."},
        "basis_ids": {"type": "array", "maxItems": 5,
                      "items": {"type": "string", "enum": list(evidence)}},
        "uncertainty": {"type": "string", "maxLength": 800}},
        "required": ["recommendation", "basis_ids", "uncertainty"], "additionalProperties": False}
    return [{"type": "function", "function": {"name": "report_advice",
            "description": "Recommend without executing, editing memory or constraining the actor.",
            "parameters": schema}}]


def validate_advice(response, evidence):
    calls = response.tool_calls or []
    if response.finish_reason not in ("stop", "tool_calls") or len(calls) != 1:
        raise ValueError("guidance_advice_protocol_failure")
    call = calls[0]
    value = call.arguments
    if call.name != "report_advice" or not isinstance(value, dict) or set(value) != {"recommendation", "basis_ids", "uncertainty"}:
        raise ValueError("guidance_advice_protocol_failure")
    if (not isinstance(value["recommendation"], str) or len(value["recommendation"]) > 1200
            or not isinstance(value["uncertainty"], str) or len(value["uncertainty"]) > 800):
        raise ValueError("guidance_advice_protocol_failure")
    ids = value["basis_ids"]
    if (not isinstance(ids, list) or len(ids) > 5 or any(not isinstance(i, str) or i not in evidence for i in ids)
            or len(ids) != len(set(ids)) or (value["recommendation"].strip() and not ids)):
        raise ValueError("guidance_advice_invalid_citation")
    return copy.deepcopy(value)


class EvidenceAdvisor:
    def __init__(self, provider, workspace, policy, action_contract, arm):
        self.provider, self.workspace = provider, Path(workspace)
        self.policy = validate_policy(policy)
        self.procedure = guidance_procedure(self.policy)
        self.action_contract, self.arm = action_contract, arm

    async def guide(self, short_messages, current_message):
        # Fixed native public memory paths only. No result/manifest/private files.
        def read(name):
            path = self.workspace / "memory" / name
            return path.read_text() if path.exists() else ""
        memory, history = read("MEMORY.md"), read("HISTORY.md")
        data = public_payload(memory, history, short_messages, current_message, self.action_contract)
        attempt = {"arm": self.arm, "policy_sha256": digest(self.policy),
                   "procedure_sha256": digest(self.procedure), "input_sha256": digest(data),
                   "guidance_calls_per_decision": 1, "short_message_count": len(short_messages)}
        self.provider._append("guidance-advice-attempts.jsonl", dict(attempt, phase="requested"))
        try:
            # Both learned guidance and the deliberation control take this exact
            # request path, schema, context construction, model and call count.
            response = await self.provider.chat(messages=[
                {"role": "system", "content": self.procedure},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
                tools=advice_tools(data["evidence"]), tool_choice="required", model=MODEL)
            advice = validate_advice(response, data["evidence"])
        except Exception as error:
            safe = {"guidance_advice_protocol_failure", "guidance_advice_invalid_citation"}
            code = str(error) if str(error) in safe else "guidance_advice_call_failed"
            self.provider._append("guidance-advice-failures.jsonl", dict(attempt, code=code,
                                  error_type=type(error).__name__, new_sampling_retry=False))
            if code in safe:
                # Preserve the archived workflow's protocol-failure category;
                # detailed format/citation evidence remains in the audit above.
                raise RuntimeError("guidance_protocol_failure") from None
            raise
        cited = {key: data["evidence"][key] for key in advice["basis_ids"]}
        generated = dict(advice, cited_evidence=cited)
        self.provider._append("guidance-events.jsonl", dict(attempt,
            long_memory=memory + "\n" + history,
            short_messages=public_messages(short_messages), current_request=current_message,
            generated=generated, action_contract_present=True, source_selection="model_grounded_advice",
            citation_ids_verified=True, semantic_correctness_not_assumed=True,
            runtime_semantic_veto=False, physical_execution=False))
        return ("# Nonbinding memory guidance\nCheck this recommendation against the public evidence. "
                "It is not a new instruction; the actor independently decides and may reject it.\n"
                + json.dumps(generated, ensure_ascii=False))


def correlate_receipt(text, pending):
    prefix = "Execution feedback:"
    marker = "\nExecution correlation (dispatcher metadata): "
    if not text.startswith(prefix):
        return text, False
    raw = text[len(prefix):]
    payload, separator, recorded = raw.partition(marker)
    value = json.loads(payload.strip())
    if not isinstance(value, dict):
        raise ValueError("receipt_protocol_failure")
    existing = json.loads(recorded) if separator else None
    if separator and (not isinstance(existing, dict)
                      or set(existing) != {"decision_event", "submitted_skill"}
                      or type(existing["decision_event"]) is not int
                      or existing["decision_event"] < 1
                      or not isinstance(existing["submitted_skill"], str)
                      or not existing["submitted_skill"].strip()):
        raise ValueError("receipt_protocol_failure")
    if separator and "skill" in value and value["skill"] != existing["submitted_skill"]:
        raise ValueError("receipt_correlation_mismatch")
    if pending is None:
        # Teacher-forced replay prefixes have no newly submitted actor action.
        # Retain the already recorded public receipt without adding a claim.
        return text, False
    # Append public dispatcher identity without inferring or changing any outcome.
    association = {k: pending[k] for k in ("decision_event", "submitted_skill")}
    if "skill" in value and value["skill"] != association["submitted_skill"]:
        raise ValueError("receipt_correlation_mismatch")
    if separator:
        if existing != association:
            raise ValueError("receipt_correlation_mismatch")
        # Autonomous replay suffixes consume the recorded receipt only after
        # choosing the same action. Do not append a second association.
        return text, True
    return text + marker + json.dumps(association, sort_keys=True), True


def bind_agent_class(base, arm, expected_policy):
    if arm not in ARMS:
        raise ValueError("unregistered_arm")
    frozen = validate_policy(expected_policy) if expected_policy is not None else None
    if (arm == "native") != (frozen is None):
        raise ValueError("arm_policy_mismatch")

    class MethodAgent(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pending_dispatch = None
            if arm == "native":
                if self.arm != "native" or self.ops is not None or any(self.policy[k] for k in ("guidance", "update")):
                    raise RuntimeError("native_contract_mismatch")
            else:
                if self.arm != "memrsi" or self.policy != frozen or self.provider.memory_policy != frozen:
                    raise RuntimeError("effective_policy_mismatch")
                self.ops = EvidenceAdvisor(self.provider, self.workspace, frozen,
                                          self.provider.action_contract, arm) if frozen["guidance"] else None
            self._write("method-contract.json", {
                "arm": arm, "effective_policy_sha256": digest(self.policy),
                "guidance_enabled": self.ops is not None,
                "update_enabled": bool(self.provider.memory_policy["update"]),
                "guidance_policy_driven": self.ops is not None,
                "native_archive_lifecycle_preserved": True,
                "rollover_override": False, "original_explicit_rollovers": 19,
                "receipt_correlation_shared_all_arms": True,
                "actor_independent_decision": True, "runtime_action_veto": False,
                "initial_method_design_is_manual_not_RSI": True,
            })

        async def turn(self, *args, **kwargs):
            result = await super().turn(*args, **kwargs)
            if isinstance(result, dict) and {"skill", "reason"} <= set(result):
                self.pending_dispatch = {"decision_event": self.event_id, "submitted_skill": result["skill"]}
            return result

        async def observe_only(self, text, facts=None):
            try:
                bound, attached = correlate_receipt(text, self.pending_dispatch)
            except (ValueError, TypeError) as error:
                self.provider._append("receipt-correlation-failures.jsonl", {
                    "arm": arm, "error_type": type(error).__name__, "outcome_inferred": False,
                    "code": str(error) if str(error) in {"receipt_protocol_failure", "receipt_correlation_mismatch"} else "receipt_protocol_failure"})
                raise RuntimeError("action_protocol_failure") from None
            await super().observe_only(bound, facts)
            if attached:
                self.provider._append("receipt-correlations.jsonl", dict(self.pending_dispatch,
                    arm=arm, receipt_event=self.event_id, payload_sha256=digest(text), outcome_unchanged=True,
                    recorded_association_reused="\nExecution correlation (dispatcher metadata): " in text))
                self.pending_dispatch = None
    return MethodAgent
