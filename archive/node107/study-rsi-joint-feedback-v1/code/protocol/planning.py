"""Frozen LIBERO five-arm planning helpers. No model calls or process launches.

Use the original feedback_workflow and its original 19 /new boundaries. This
module only defines conditions, policies, and evidence required before dispatch.
"""
import copy
import hashlib
import itertools
import json

ARMS = ("native", "G_only", "U_only", "GU_parent", "GU_learned")
DEFAULT_HISTORIES = ("ABCED", "ABECD", "ACBDE", "ACBED", "ACDEB", "ACEDB")
DEFAULT_VARIANTS = (0, 1)
PROPOSED_INIT_IDS = (20, 21)
PRIMARY_COMPARISONS = (("GU_learned", "G_only"),
                       ("GU_learned", "U_only"),
                       ("GU_learned", "GU_parent"))


def digest(value):
    """Match the archived memory_policy.digest JSON encoding."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != {"schema", "guidance", "update"}:
        raise ValueError("policy_schema")
    if value["schema"] != 1 or any(not isinstance(value[k], str) or
                                  len(value[k]) > 1800 for k in ("guidance", "update")):
        raise ValueError("policy_schema_or_length")
    return copy.deepcopy(value)


def policy_for(parent, learned, arm):
    if arm not in ARMS:
        raise ValueError("unregistered_arm")
    if arm == "native":
        return None
    # Singles remove one component from the FINAL learned method, so each
    # conditional effect compares byte-identical remaining G or U procedures.
    result = validate_policy(parent if arm == "GU_parent" else learned)
    if not result["guidance"] or not result["update"]:
        raise ValueError("parent_and_learned_must_contain_both_operators")
    if arm == "G_only":
        result["update"] = ""
    if arm == "U_only":
        result["guidance"] = ""
    return result


def bind_agent_class(base, arm, expected_policy):
    """Bind the existing TwentyAgent without altering turn/observe/rollover.

    Pass the arm's exported policy path to feedback_workflow. Its workflow arm
    is native for native, memrsi for every other registered treatment. Clearing
    guidance alone is insufficient: U_only must also set ops=None.
    """
    if arm not in ARMS:
        raise ValueError("unregistered_arm")
    frozen = validate_policy(expected_policy) if expected_policy is not None else None

    class FrozenComponentAgent(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if arm == "native":
                if self.arm != "native" or self.ops is not None or self.policy["update"]:
                    raise RuntimeError("native_contract_mismatch")
            else:
                if self.arm != "memrsi" or self.policy != frozen:
                    raise RuntimeError("effective_policy_mismatch")
                if not frozen["guidance"]:
                    self.ops = None
                elif self.ops is None:
                    raise RuntimeError("enabled_guidance_missing")
                if self.provider.memory_policy != frozen:
                    raise RuntimeError("provider_policy_mismatch")
            self._write("libero-factorial-contract.json", {
                "arm": arm,
                "effective_policy_sha256": digest(self.policy),
                "guidance_enabled": self.ops is not None,
                "update_enabled": bool(self.provider.memory_policy["update"]),
                "native_archive_lifecycle_preserved": True,
                "explicit_rollover_every_original_session": True,
                "turn_observe_receipts_action_contract_unchanged": True,
                "evaluation_policy_learning": False,
            })
    return FrozenComponentAgent


def transform_history(original_plan, history):
    """Exactly feedback_protocol.plan's transformation, without its old whitelist."""
    if len(history) != 5 or set(history) != set("ABCDE"):
        raise ValueError("invalid_history_permutation")
    p = copy.deepcopy(original_plan("alpha"))
    initial = list(history)
    changed = [initial[1], initial[0]] + initial[2:]
    final = changed[:2] + changed[3:] + [changed[2]]
    p["initial_message"] = p["initial_message"].replace("A, B, C, D, E.", ", ".join(initial) + ".")
    p["updates_after_session"][6] = "Change the eventual completion priority for tables A through E to: " + ", ".join(changed) + ". This replaces the earlier order."
    p["updates_after_session"][8] = "One more priority change: finish the remaining table services in this order: " + ", ".join(final) + ". This is the current order."
    for step in p["sessions"]:
        if step["kind"] == "recovery":
            step["expected_private"] = "serve_" + final[(step["session"] - 11) // 2]
    p.update(history=history, final_order_private=final)
    return p


def bind_registered_plan(original_plan, histories=DEFAULT_HISTORIES):
    """Assign this closure to feedback_workflow.plan; never edit archived code."""
    allowed = frozenset(histories)
    def registered(history):
        if history not in allowed:
            raise ValueError("unregistered_test_history")
        return transform_history(original_plan, history)
    return registered


def conditions(histories=DEFAULT_HISTORIES, variants=DEFAULT_VARIANTS,
               init_ids=PROPOSED_INIT_IDS):
    if len(histories) != 6 or len(set(histories)) != 6:
        raise ValueError("six_distinct_histories_required")
    if len(variants) != 2 or len(set(variants)) != 2:
        raise ValueError("two_distinct_variants_required")
    if len(init_ids) != 2 or len(set(init_ids)) != 2 or any(i < 0 for i in init_ids):
        raise ValueError("two_distinct_valid_initial_states_required")
    return [{"condition_id": f"h{h}-v{v}-i{i}", "history": h, "variant": v,
             "init": i, "repeat": 0}
            for h, v, i in itertools.product(histories, variants, init_ids)]


def selection_audit(parent, learned, provenance):
    parent, learned = validate_policy(parent), validate_policy(learned)
    required = ("source_study", "source_parent_sha256", "learning_behavior_sha256",
                "evaluation_behavior_sha256", "trained_only_on_development",
                "heldout_validation_passed", "frozen_before_this_evaluation")
    missing = [k for k in required if k not in provenance]
    blockers = ["missing_selection_evidence:" + k for k in missing]
    if not missing:
        if provenance["source_parent_sha256"] != digest(parent):
            blockers.append("learned_parent_is_not_this_parent")
        # Match behavior-critical archived source, not deployment paths or EGL
        # wiring. Keep the full current wiring hash separately in make_plan.
        if provenance["learning_behavior_sha256"] != provenance["evaluation_behavior_sha256"]:
            blockers.append("behavior_changed_between_learning_and_evaluation")
        for k in ("trained_only_on_development", "heldout_validation_passed",
                  "frozen_before_this_evaluation"):
            if provenance[k] is not True:
                blockers.append(k)
    changed = parent != learned
    return {"parent_sha256": digest(parent), "learned_sha256": digest(learned),
            "policy_changed": changed, "can_test_rsi_improvement": changed and not blockers,
            "changed_operators": [k for k in ("guidance", "update") if parent[k] != learned[k]],
            "blockers": blockers,
            "identical_policy_rule": "Do not relabel a parent repetition as RSI gain."}


def make_plan(parent, learned, provenance, *, init_audit=None, runtime_sha256=None,
              budget_sha256=None, orders_sha256=None):
    cases = conditions()
    selection = selection_audit(parent, learned, provenance)
    blockers = list(selection["blockers"])
    if not selection["policy_changed"]:
        blockers.append("no_changed_qualified_learned_policy")
    if not all((runtime_sha256, budget_sha256, orders_sha256)):
        blockers.append("freeze_runtime_budget_and_orders_hashes")
    if not init_audit or init_audit.get("all_required_tasks_have_indices") is not True:
        blockers.append("initial_state_availability_not_verified")
    if not init_audit or init_audit.get("historical_exposure_audited") is not True:
        blockers.append("historical_exposure_not_audited")
    if not init_audit or init_audit.get("optimizer_training_conditions_disjoint") is not True:
        blockers.append("optimizer_training_overlap_not_audited")
    if init_audit and init_audit.get("init_ids") != list(PROPOSED_INIT_IDS):
        blockers.append("initial_state_audit_mismatch")
    jobs = []
    for index, case in enumerate(cases):
        order = ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)]
        for arm in order:
            jobs.append(dict(case, arm=arm, workflow_arm="native" if arm == "native" else "memrsi",
                             trial_id=f"{case['condition_id']}/{arm}"))
    policies = {a: policy_for(parent, learned, a) for a in ARMS}
    return {"version": "libero-five-arm-20261023", "status": "ready" if not blockers else "prepared_not_launchable",
            "dispatch_blockers": blockers, "arms": list(ARMS), "conditions": cases,
            "planned_conditions": 24, "planned_episodes": 120, "jobs": jobs,
            "policy_sha256": {a: digest(p) if p is not None else None for a, p in policies.items()},
            "selection_audit": selection, "runtime_sha256": runtime_sha256,
            "budget_sha256": budget_sha256, "orders_sha256": orders_sha256,
            "primary_comparisons": PRIMARY_COMPARISONS,
            "secondary_comparisons": [("GU_learned", "native"), ("GU_parent", "native"), ("G_only", "native"), ("U_only", "native")],
            "protocol": "Original LIBERO feedback_workflow; 20 sessions, 19 native /new boundaries, 7 planned checkpoints.",
            "scope": "Six registered mission orders absent from identified optimizer records, two kitchen rotations and two physical initial states disjoint from optimizer init0/1 training. Historical init0..49 exposure prevents a globally unseen physical-scene or unseen-task-family claim.",
            "stopping_rule": "One immutable evaluation. No outcome-driven reruns or redesigns. Preserve every failure. First technical failure pauses new dispatch for root-cause repair.",
            "technical_retry_rule": "Only an evidenced infrastructure repair may resume the same registered job; retain every attempt and lifetime limits; never rerun capability failures.",
            "analysis": "Report all 24 planned episodes per arm, successes, technical/physical/decision failures, paired discordances, checkpoint coverage, calls/tokens/latency. Repeated histories are not independent task families.",
            "rsi_claim": "Learned must be automatically generated from this parent using development only, pass reserved validation, then remain frozen during this evaluation. If only U changed, joint-rule RSI gain does not establish independent G learning."}
