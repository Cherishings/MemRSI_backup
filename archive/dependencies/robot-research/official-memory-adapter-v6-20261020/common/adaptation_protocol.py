"""Pure orchestration guards for a prospective visual-memory RSI experiment.

No simulator, model, prompt optimizer or remote job is implemented here. Official
full-trajectory results are consumed *outside* the acting agent. Development
results alone can be exported to an optimizer. Validation is a one-shot gate,
and final test results can only be summarized. The protocol neither retries a
failed capability case nor claims statistical significance.
"""
import copy
import json
from pathlib import Path
import re


BENCHMARKS = ("rmbench", "remem")
SPLITS = {
    "development": tuple(range(3000, 3012)),
    "validation": tuple(range(3100, 3112)),
    "test": tuple(range(3200, 3248)),
}
METHODS = ("native", "pre", "post")
FINAL_METHODS = ("native", "post")
INHERITED_CALLS = 8986
DEFAULT_TOTAL_LIMIT = 9745
MAX_ROUNDS = 2
VALID_STATUSES = frozenset({
    "success", "task_failure", "decision_failure", "physical_failure",
    "protocol_failure", "capacity_failure", "budget_failure",
})
UNRESOLVED_STATUSES = frozenset({
    "technical_failure", "infrastructure_failure", "unclassified_failure",
    "incomplete", "running",
})
PROTECTED_FAILURES = frozenset({"protocol_failure", "capacity_failure"})
ROW_FIELDS = frozenset({
    "benchmark", "seed", "method", "split", "status", "official_success",
    "policy_sha256",
})


def _positive_integer(value, label, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ValueError(label)
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("policy_sha256")
    return value


def _benchmarks(values):
    values = tuple(values)
    if not values or len(set(values)) != len(values) or set(values) - set(BENCHMARKS):
        raise ValueError("benchmark_scope")
    return tuple(b for b in BENCHMARKS if b in values)


class CumulativeBudget:
    """Validate inherited totals; planning checks do not reset or spend calls.

    ``authorization_file`` must be an explicit authorization artifact containing
    exactly ``authorized_total``. This helper cannot create an authorization or
    infer one from a proposal. Actual concurrent providers must continue using
    their existing locked cumulative ledger, rather than independent instances
    of this local planning object.
    """
    def __init__(self, calls=INHERITED_CALLS, authorization_file=None):
        _positive_integer(calls, "cumulative_calls")
        if calls < INHERITED_CALLS:
            raise ValueError("learning_budget_reset")
        limit = DEFAULT_TOTAL_LIMIT
        if authorization_file is not None:
            data = json.loads(Path(authorization_file).read_text())
            if not isinstance(data, dict) or set(data) != {"authorized_total"}:
                raise ValueError("authorization_fields")
            limit = _positive_integer(data["authorized_total"], "authorized_total")
        if limit < calls:
            raise ValueError("cumulative_calls_exceed_authorized_total")
        self.calls, self.limit = calls, limit

    @property
    def remaining(self):
        return self.limit - self.calls

    def can_plan(self, development_calls, validation_reserve_calls):
        _positive_integer(development_calls, "development_call_plan", allow_zero=True)
        _positive_integer(validation_reserve_calls, "validation_call_reserve", allow_zero=True)
        return development_calls + validation_reserve_calls <= self.remaining

    def record_calls(self, count=1):
        _positive_integer(count, "call_count")
        if count > self.remaining:
            raise RuntimeError("learning_budget_exhausted")
        self.calls += count
        return self.snapshot()

    def snapshot(self):
        return {"calls": self.calls, "limit": self.limit, "remaining": self.remaining,
                "baseline": INHERITED_CALLS, "budget_reset": False}


def complete_records(rows, split, methods, benchmarks=BENCHMARKS, expected_policies=None):
    """Reject missing/duplicate cases, contamination, and unresolved outcomes.

    Callers normalize their official result schemas before invoking this API.
    In particular, an undifferentiated ``agent_failure`` is not silently treated
    as an ordinary task error, because it could conceal protocol/capacity faults.
    No model assertion is accepted as the official outcome.
    """
    if split not in SPLITS:
        raise ValueError("unknown_split")
    methods = tuple(methods)
    if not methods or len(set(methods)) != len(methods) or set(methods) - set(METHODS):
        raise ValueError("method_scope")
    benchmarks = _benchmarks(benchmarks)
    if not isinstance(rows, list):
        raise ValueError("records_must_be_list")
    expected = {(b, s, m) for b in benchmarks for s in SPLITS[split] for m in methods}
    seen = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise ValueError("record_fields")
        if row["split"] != split:
            raise ValueError("split_contamination")
        _positive_integer(row["seed"], "seed")
        key = row["benchmark"], row["seed"], row["method"]
        if key not in expected:
            raise ValueError("out_of_split_case")
        if key in seen:
            raise ValueError("duplicate_case")
        _hash(row["policy_sha256"])
        if expected_policies and row["policy_sha256"] != expected_policies[row["method"]]:
            raise ValueError("policy_changed")
        if row["status"] in UNRESOLVED_STATUSES:
            raise ValueError("unresolved_case")
        if row["status"] not in VALID_STATUSES:
            raise ValueError("unclassified_result_status")
        if type(row["official_success"]) is not bool:
            raise ValueError("official_success_must_be_bool")
        if row["official_success"] != (row["status"] == "success"):
            raise ValueError("official_result_inconsistent")
        seen[key] = copy.deepcopy(row)
    if set(seen) != expected:
        raise ValueError("incomplete_case_manifest")
    return [seen[k] for k in sorted(seen)]


def paired_effect(rows, split, benchmarks=BENCHMARKS, expected_policies=None):
    rows = complete_records(rows, split, ("pre", "post"), benchmarks, expected_policies)
    paired = {}
    for r in rows:
        paired.setdefault((r["benchmark"], r["seed"]), {})[r["method"]] = r
    summaries = {}
    new_failures = []
    for benchmark in _benchmarks(benchmarks):
        group = [v for (b, _), v in paired.items() if b == benchmark]
        summaries[benchmark] = {
            "pairs": len(group),
            "pre_success": sum(g["pre"]["official_success"] for g in group),
            "post_success": sum(g["post"]["official_success"] for g in group),
            "improvements": sum(not g["pre"]["official_success"] and g["post"]["official_success"] for g in group),
            "regressions": sum(g["pre"]["official_success"] and not g["post"]["official_success"] for g in group),
        }
    for (benchmark, seed), g in sorted(paired.items()):
        status = g["post"]["status"]
        if status in PROTECTED_FAILURES and g["pre"]["status"] != status:
            new_failures.append({"benchmark": benchmark, "seed": seed, "status": status})
    pre = sum(r["official_success"] for r in rows if r["method"] == "pre")
    post = sum(r["official_success"] for r in rows if r["method"] == "post")
    return {
        "split": split, "planned_pairs": len(paired), "valid_pairs": len(paired),
        "pre_success": pre, "post_success": post, "success_gain": post - pre,
        "new_protocol_or_capacity_failures": new_failures, "by_benchmark": summaries,
        "score_source": "official_full_trajectory_result_outside_actor",
        "statistical_significance_claimed": False,
    }


class AdaptationProtocol:
    """One candidate per round, at most two rounds, then one reserved gate.

    ``pre``/``post`` denote parent/candidate inside a development round. For the
    reserved validation they denote the original baseline rule and final
    selected rule. The final test compares native and post only; it measures
    the whole method, not an isolated evolution effect. Rules can be learned by
    an explicit one-element benchmark scope; that is recorded in the manifest.
    """
    def __init__(self, baseline_policy_sha256, benchmarks=BENCHMARKS, budget=None):
        baseline = _hash(baseline_policy_sha256)
        self.benchmarks = _benchmarks(benchmarks)
        self.budget = budget if budget is not None else CumulativeBudget()
        self.initial_policy = self.current_policy = baseline
        self.candidate_policy = None
        self.phase = "ready_for_proposal"
        self.rounds = []
        self.proposed_hashes = set()
        self.validation_used = False
        self.validation_result = None
        self.final_result = None
        self.termination_reason = None
        self.selection_basis = None
        self.evolution_supported = False

    def manifest(self):
        return {
            "schema": "visual_rsi_adaptation_protocol_v1",
            "benchmarks": list(self.benchmarks),
            "splits": {k: list(v) for k, v in SPLITS.items()},
            "max_rounds": MAX_ROUNDS, "max_candidates_per_round": 1,
            "final_methods": list(FINAL_METHODS),
            "final_test_claim_scope": "whole_method_vs_native_not_isolated_evolution",
            "initial_policy_sha256": self.initial_policy,
            "current_policy_sha256": self.current_policy,
            "candidate_policy_sha256": self.candidate_policy,
            "phase": self.phase, "rounds": copy.deepcopy(self.rounds),
            "validation_used": self.validation_used,
            "validation_result": copy.deepcopy(self.validation_result),
            "final_result": copy.deepcopy(self.final_result),
            "termination_reason": self.termination_reason,
            "selection_basis": self.selection_basis,
            "evolution_supported": self.evolution_supported,
            "new_domain_rule_adopted": self.evolution_supported,
            "evolution_support_scope": "development_gain_and_reserved_nondecrease_not_significance",
            "accepted_development_success_gain": sum(r["effect"]["success_gain"] for r in self.rounds if r["accepted"]),
            "reserved_validation_success_gain": self.validation_result["effect"]["success_gain"] if self.validation_result else None,
            "budget": self.budget.snapshot(),
            "optimizer_allowed_split": "development",
            "implemented_scope": "orchestration_guards_not_model_or_physical_learner",
        }

    def propose(self, candidate_policy_sha256):
        if self.phase != "ready_for_proposal" or len(self.rounds) >= MAX_ROUNDS:
            raise RuntimeError("proposal_not_allowed")
        candidate = _hash(candidate_policy_sha256)
        if candidate == self.current_policy or candidate in self.proposed_hashes:
            raise ValueError("unchanged_or_repeated_candidate")
        if self.budget.remaining == 0:
            # Lack of authorized calls is not evidence of no improvement.
            # Leave state and prior adoption intact for explicit budget resume.
            raise RuntimeError("learning_budget_exhausted")
        self.proposed_hashes.add(candidate)
        self.candidate_policy = candidate
        self.phase = "awaiting_development"
        return self.manifest()

    def optimizer_development_records(self, rows, methods=("pre",)):
        """Only validated development projections can leave for the optimizer."""
        if self.phase not in ("ready_for_proposal", "awaiting_development"):
            raise RuntimeError("optimizer_closed")
        expected = {"pre": self.current_policy}
        if "post" in methods:
            if self.candidate_policy is None:
                raise ValueError("no_candidate")
            expected["post"] = self.candidate_policy
        if "native" in methods:
            raise ValueError("native_not_optimizer_parent")
        return complete_records(rows, "development", methods, self.benchmarks, expected)

    def finish_round(self, rows):
        if self.phase != "awaiting_development":
            raise RuntimeError("development_comparison_not_allowed")
        effect = paired_effect(rows, "development", self.benchmarks,
                               {"pre": self.current_policy, "post": self.candidate_policy})
        accepted = effect["success_gain"] > 0 and not effect["new_protocol_or_capacity_failures"]
        self.rounds.append({"round": len(self.rounds) + 1,
                            "parent_policy_sha256": self.current_policy,
                            "candidate_policy_sha256": self.candidate_policy,
                            "accepted": accepted, "effect": effect})
        if accepted:
            self.current_policy = self.candidate_policy
        self.candidate_policy = None
        self.phase = "ready_for_proposal"
        if len(self.rounds) == MAX_ROUNDS:
            self.freeze()
        return self.manifest()

    def freeze(self):
        if self.phase != "ready_for_proposal" or not self.rounds:
            raise RuntimeError("freeze_not_allowed")
        if self.current_policy == self.initial_policy:
            self.phase = "no_improvement"
            self.termination_reason = "no_development_candidate_adopted"
        else:
            self.phase = "awaiting_validation"
        return self.manifest()

    def validate_once(self, rows):
        if self.phase != "awaiting_validation" or self.validation_used:
            raise RuntimeError("validation_already_used_or_not_allowed")
        effect = paired_effect(rows, "validation", self.benchmarks,
                               {"pre": self.initial_policy, "post": self.current_policy})
        self.validation_used = True
        # No perfection requirement: nondecrease on complete reserved cases,
        # while retaining the same protocol/capacity safety condition as dev.
        passed = effect["success_gain"] >= 0 and not effect["new_protocol_or_capacity_failures"]
        self.validation_result = {"passed": passed, "effect": effect,
                                  "candidate_policy_sha256": self.current_policy}
        if passed:
            self.phase = "ready_for_final_test"
            self.selection_basis = "validated_candidate"
            self.evolution_supported = True
        else:
            self.current_policy = self.initial_policy
            self.phase = "no_improvement"
            self.termination_reason = "reserved_validation_not_passed"
        return self.manifest()

    def select_parent_fallback(self):
        """Finish the requested formal cohort even when local adaptation fails.

        The unchanged initial rule needs no redundant parent-versus-parent
        reserved validation. Failed candidate evidence remains in the manifest;
        it cannot be used for another round of tuning.
        """
        if (self.phase != "no_improvement" or self.current_policy != self.initial_policy
                or self.candidate_policy is not None):
            raise RuntimeError("parent_fallback_not_allowed")
        self.selection_basis = "unchanged_parent_fallback"
        self.evolution_supported = False
        self.phase = "ready_for_final_test"
        return self.manifest()

    def record_final_test(self, rows, native_policy_sha256):
        if self.phase != "ready_for_final_test" or self.final_result is not None:
            raise RuntimeError("final_test_not_allowed")
        if self.selection_basis not in ("validated_candidate", "unchanged_parent_fallback"):
            raise RuntimeError("final_selection_basis_missing")
        if self.selection_basis == "unchanged_parent_fallback" and self.current_policy != self.initial_policy:
            raise RuntimeError("fallback_policy_must_equal_initial")
        values = complete_records(rows, "test", FINAL_METHODS, self.benchmarks,
            {"native": _hash(native_policy_sha256), "post": self.current_policy})
        self.final_result = {
            "planned_cases_per_method": len(SPLITS["test"]) * len(self.benchmarks),
            "by_benchmark": {b: {m: {
                "cases": len(SPLITS["test"]),
                "success": sum(r["official_success"] for r in values
                               if r["benchmark"] == b and r["method"] == m),
            } for m in FINAL_METHODS} for b in self.benchmarks},
            "score_source": "official_full_trajectory_result_outside_actor",
            "claim_scope": "whole_method_vs_native_not_isolated_evolution",
            "statistical_significance_claimed": False,
            "selection_basis": self.selection_basis,
            "evolution_supported": self.evolution_supported,
            "new_domain_rule_adopted": self.evolution_supported,
            "evolution_support_scope": "development_gain_and_reserved_nondecrease_not_significance",
            "accepted_development_success_gain": sum(r["effect"]["success_gain"] for r in self.rounds if r["accepted"]),
            "reserved_validation_success_gain": self.validation_result["effect"]["success_gain"] if self.validation_result else None,
        }
        self.phase = "complete"
        return self.manifest()

    def stop_without_improvement(self, reason):
        if self.phase in ("complete", "no_improvement"):
            raise RuntimeError("protocol_already_terminal")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("termination_reason")
        self.current_policy = self.initial_policy
        self.candidate_policy = None
        self.phase = "no_improvement"
        self.termination_reason = reason
        self.selection_basis = None
        self.evolution_supported = False
        return self.manifest()
