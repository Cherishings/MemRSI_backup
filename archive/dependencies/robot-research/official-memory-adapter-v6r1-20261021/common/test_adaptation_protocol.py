import copy
import json
from pathlib import Path
import tempfile
import unittest

from adaptation_protocol import (
    AdaptationProtocol, BENCHMARKS, CumulativeBudget, DEFAULT_TOTAL_LIMIT,
    FINAL_METHODS, INHERITED_CALLS, METHODS, SPLITS, complete_records, paired_effect,
)


PARENT = "a" * 64
CANDIDATE = "b" * 64
SECOND = "c" * 64
NATIVE = "d" * 64


def records(split="development", methods=("pre", "post"),
            benchmarks=BENCHMARKS, hashes=None, successes=None):
    hashes = hashes or {"pre": PARENT, "post": CANDIDATE, "native": NATIVE}
    successes = successes or {}
    return [{"benchmark": b, "seed": s, "method": m, "split": split,
             "status": "success" if s in successes.get((b, m), set()) else "task_failure",
             "official_success": s in successes.get((b, m), set()),
             "policy_sha256": hashes[m]}
            for b in benchmarks for s in SPLITS[split] for m in methods]


def improvements(split="development", hashes=None):
    return records(split, hashes=hashes,
                   successes={(b, "post"): {SPLITS[split][0]} for b in BENCHMARKS})


class BudgetTests(unittest.TestCase):
    def test_budget_inherits_8986_of_9745_without_reset(self):
        budget = CumulativeBudget()
        self.assertEqual(budget.remaining, 759)
        before = budget.snapshot()
        self.assertTrue(budget.can_plan(700, 59))
        self.assertFalse(budget.can_plan(700, 60))
        self.assertEqual(before, budget.snapshot())
        budget.record_calls(759)
        self.assertEqual(budget.calls, DEFAULT_TOTAL_LIMIT)
        with self.assertRaisesRegex(RuntimeError, "learning_budget_exhausted"):
            budget.record_calls()
        self.assertEqual(budget.calls, DEFAULT_TOTAL_LIMIT)

    def test_reset_or_unapproved_expansion_is_not_silent(self):
        for calls in (0, INHERITED_CALLS - 1, DEFAULT_TOTAL_LIMIT + 1, True):
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                CumulativeBudget(calls)
        with self.assertRaises(ValueError):
            CumulativeBudget().record_calls(0)

    def test_only_explicit_total_authorization_changes_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authorization.json"
            path.write_text(json.dumps({"authorized_total": 10000}))
            budget = CumulativeBudget(calls=9745, authorization_file=path)
            self.assertEqual(budget.limit, 10000)
            self.assertEqual(budget.calls, 9745)
            self.assertEqual(budget.remaining, 255)
            path.write_text(json.dumps({"additional_calls": 4000}))
            with self.assertRaisesRegex(ValueError, "authorization_fields"):
                CumulativeBudget(authorization_file=path)
            path.write_text(json.dumps({"authorized_total": True}))
            with self.assertRaises(ValueError):
                CumulativeBudget(authorization_file=path)


class ManifestTests(unittest.TestCase):
    def test_exact_manifest_and_official_score(self):
        values = improvements()
        result = paired_effect(values, "development")
        self.assertEqual(result["planned_pairs"], 24)
        self.assertEqual(result["valid_pairs"], 24)
        self.assertEqual(result["success_gain"], 2)
        self.assertEqual(result["pre_success"], 0)
        self.assertEqual(result["post_success"], 2)
        self.assertFalse(result["statistical_significance_claimed"])

    def test_missing_case_or_entire_benchmark_fails_closed(self):
        values = records()
        for partial in (values[:-1], [r for r in values if r["benchmark"] == "rmbench"]):
            with self.assertRaisesRegex(ValueError, "incomplete_case_manifest"):
                paired_effect(partial, "development")

    def test_duplicate_or_wrong_seed_or_split_fails_closed(self):
        values = records()
        with self.assertRaisesRegex(ValueError, "duplicate_case"):
            paired_effect(values + [values[0]], "development")
        values[0]["seed"] = 2200
        with self.assertRaisesRegex(ValueError, "out_of_split_case"):
            paired_effect(values, "development")
        values = records(); values[0]["split"] = "test"
        with self.assertRaisesRegex(ValueError, "split_contamination"):
            paired_effect(values, "development")

    def test_technical_and_ambiguous_failure_not_counted_as_ability(self):
        for status in ("technical_failure", "running", "agent_failure"):
            values = records(); values[0]["status"] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                paired_effect(values, "development")

    def test_only_official_boolean_accepted(self):
        for invalid in (1, "true", None):
            values = records(); values[0]["official_success"] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "official_success_must_be_bool"):
                paired_effect(values, "development")
        values = records(); values[0]["official_success"] = True
        with self.assertRaisesRegex(ValueError, "official_result_inconsistent"):
            paired_effect(values, "development")
        values = records(); values[0]["model_says_success"] = True
        with self.assertRaisesRegex(ValueError, "record_fields"):
            paired_effect(values, "development")

    def test_no_per_case_policy_switch(self):
        values = records(); values[0]["policy_sha256"] = SECOND
        with self.assertRaisesRegex(ValueError, "policy_changed"):
            paired_effect(values, "development", expected_policies={"pre": PARENT, "post": CANDIDATE})


class StateMachineTests(unittest.TestCase):
    def protocol_with_adoption(self):
        p = AdaptationProtocol(PARENT)
        p.propose(CANDIDATE)
        p.finish_round(improvements())
        self.assertEqual(p.current_policy, CANDIDATE)
        p.freeze()
        return p

    def test_no_100_percent_requirement_and_complete_final_result(self):
        p = self.protocol_with_adoption()
        # Both methods may fail many reserved cases; nondecrease suffices.
        p.validate_once(records("validation"))
        self.assertEqual(p.phase, "ready_for_final_test")
        outcome = p.record_final_test(records("test", FINAL_METHODS), NATIVE)
        self.assertEqual(outcome["phase"], "complete")
        self.assertEqual(outcome["final_result"]["planned_cases_per_method"], 96)
        self.assertEqual(outcome["final_result"]["by_benchmark"]["remem"]["post"]["cases"], 48)
        self.assertEqual(outcome["final_methods"], ["native", "post"])
        self.assertNotIn("pre", outcome["final_result"]["by_benchmark"]["remem"])
        self.assertEqual(outcome["final_result"]["claim_scope"], "whole_method_vs_native_not_isolated_evolution")

    def test_one_candidate_per_round_and_two_round_limit(self):
        p = AdaptationProtocol(PARENT)
        p.propose(CANDIDATE)
        with self.assertRaisesRegex(RuntimeError, "proposal_not_allowed"):
            p.propose(SECOND)
        p.finish_round(records())
        p.propose(SECOND)
        p.finish_round(records(hashes={"pre": PARENT, "post": SECOND}))
        self.assertEqual(len(p.rounds), 2)
        self.assertEqual(p.phase, "no_improvement")
        self.assertEqual(p.current_policy, PARENT)
        with self.assertRaisesRegex(RuntimeError, "proposal_not_allowed"):
            p.propose("e" * 64)
        with self.assertRaises(RuntimeError):
            p.validate_once(records("validation"))

    def test_first_adoption_retained_when_second_candidate_rejected(self):
        p = AdaptationProtocol(PARENT)
        p.propose(CANDIDATE); p.finish_round(improvements())
        p.propose(SECOND)
        p.finish_round(records(hashes={"pre": CANDIDATE, "post": SECOND}))
        self.assertEqual(p.current_policy, CANDIDATE)
        self.assertEqual(p.phase, "awaiting_validation")
        p.validate_once(records("validation"))
        self.assertEqual(p.current_policy, CANDIDATE)

    def test_strict_gain_and_no_new_protocol_or_capacity_failure(self):
        for status in ("protocol_failure", "capacity_failure"):
            p = AdaptationProtocol(PARENT); p.propose(CANDIDATE)
            values = improvements()
            row = next(r for r in values if r["method"] == "post" and r["seed"] == 2001)
            row["status"] = status
            result = p.finish_round(values)
            self.assertGreater(result["rounds"][0]["effect"]["success_gain"], 0)
            self.assertFalse(result["rounds"][0]["accepted"])
            self.assertEqual(p.current_policy, PARENT)
        p = AdaptationProtocol(PARENT); p.propose(CANDIDATE)
        self.assertFalse(p.finish_round(records())["rounds"][0]["accepted"])

    def test_matching_existing_protocol_failure_is_not_a_new_fault(self):
        p = AdaptationProtocol(PARENT); p.propose(CANDIDATE)
        values = improvements()
        for row in values:
            if row["benchmark"] == "rmbench" and row["seed"] == 2001:
                row["status"] = "protocol_failure"
        self.assertTrue(p.finish_round(values)["rounds"][0]["accepted"])

    def test_invalid_development_does_not_advance_or_erase_evidence(self):
        p = AdaptationProtocol(PARENT); p.propose(CANDIDATE)
        before = p.manifest()
        with self.assertRaises(ValueError):
            p.finish_round(improvements()[:-1])
        self.assertEqual(p.manifest(), before)

    def test_reserved_failure_retains_parent_and_cannot_loop_tune(self):
        p = self.protocol_with_adoption()
        values = records("validation", successes={(b, "pre"): {2100} for b in BENCHMARKS})
        p.validate_once(values)
        self.assertEqual(p.phase, "no_improvement")
        self.assertEqual(p.current_policy, PARENT)
        self.assertTrue(p.validation_used)
        with self.assertRaises(RuntimeError):
            p.validate_once(records("validation"))
        with self.assertRaises(RuntimeError):
            p.propose(SECOND)
        with self.assertRaises(RuntimeError):
            p.optimizer_development_records(records(methods=("pre",)))

    def test_missing_validation_does_not_create_false_adoption(self):
        p = self.protocol_with_adoption()
        with self.assertRaisesRegex(ValueError, "incomplete_case_manifest"):
            p.validate_once(records("validation")[:-1])
        self.assertFalse(p.validation_used)
        self.assertEqual(p.phase, "awaiting_validation")

    def test_optimizer_cannot_read_validation_or_test(self):
        p = AdaptationProtocol(PARENT)
        for split in ("validation", "test"):
            with self.subTest(split=split), self.assertRaisesRegex(ValueError, "split_contamination"):
                p.optimizer_development_records(records(split, ("pre",)))
        out = p.optimizer_development_records(records(methods=("pre",)))
        self.assertEqual(len(out), 24)
        self.assertTrue(all(r["split"] == "development" for r in out))
        p.propose(CANDIDATE); p.finish_round(improvements()); p.freeze()
        with self.assertRaisesRegex(RuntimeError, "optimizer_closed"):
            p.optimizer_development_records(records(methods=("pre",)))

    def test_no_test_before_gate_and_no_incomplete_final_success(self):
        p = AdaptationProtocol(PARENT)
        with self.assertRaises(RuntimeError):
            p.record_final_test(records("test", FINAL_METHODS), NATIVE)
        p = self.protocol_with_adoption(); p.validate_once(records("validation"))
        with self.assertRaisesRegex(ValueError, "incomplete_case_manifest"):
            p.record_final_test(records("test", FINAL_METHODS)[:-1], NATIVE)
        self.assertIsNone(p.final_result)
        self.assertEqual(p.phase, "ready_for_final_test")

    def test_budget_exhaustion_preserves_state_without_claiming_no_gain(self):
        p = AdaptationProtocol(PARENT, budget=CumulativeBudget(DEFAULT_TOTAL_LIMIT))
        with self.assertRaisesRegex(RuntimeError, "learning_budget_exhausted"):
            p.propose(CANDIDATE)
        self.assertEqual(p.phase, "ready_for_proposal")
        self.assertIsNone(p.termination_reason)
        self.assertEqual(p.budget.calls, DEFAULT_TOTAL_LIMIT)
        with self.assertRaises(RuntimeError):
            p.propose(CANDIDATE)

    def test_explicit_single_benchmark_scope(self):
        p = AdaptationProtocol(PARENT, benchmarks=("remem",))
        p.propose(CANDIDATE)
        values = [r for r in improvements() if r["benchmark"] == "remem"]
        p.finish_round(values); p.freeze()
        p.validate_once(records("validation", benchmarks=("remem",)))
        self.assertEqual(p.manifest()["benchmarks"], ["remem"])
        self.assertEqual(p.validation_result["effect"]["planned_pairs"], 12)

    def test_no_gain_fallback_completes_full_test_without_redundant_validation(self):
        p = AdaptationProtocol(PARENT)
        with self.assertRaisesRegex(RuntimeError, "parent_fallback_not_allowed"):
            p.select_parent_fallback()
        p.propose(CANDIDATE); p.finish_round(records()); p.freeze()
        p.select_parent_fallback()
        self.assertFalse(p.validation_used)
        result = p.record_final_test(records("test", FINAL_METHODS,
                                    hashes={"native": NATIVE, "post": PARENT}), NATIVE)
        self.assertEqual(result["phase"], "complete")
        self.assertEqual(result["final_result"]["selection_basis"], "unchanged_parent_fallback")
        self.assertFalse(result["final_result"]["new_domain_rule_adopted"])
        self.assertFalse(result["final_result"]["evolution_supported"])
        self.assertIsNone(result["final_result"]["reserved_validation_success_gain"])

    def test_failed_reserve_fallback_preserves_negative_result_and_cannot_tune(self):
        p = self.protocol_with_adoption()
        p.validate_once(records("validation", successes={(b, "pre"): {2100} for b in BENCHMARKS}))
        negative = copy.deepcopy(p.validation_result)
        p.select_parent_fallback()
        self.assertEqual(p.validation_result, negative)
        self.assertFalse(negative["passed"])
        self.assertEqual(p.current_policy, PARENT)
        with self.assertRaises(RuntimeError): p.propose(SECOND)
        with self.assertRaises(RuntimeError): p.validate_once(records("validation"))
        result = p.record_final_test(records("test", FINAL_METHODS,
                                    hashes={"native": NATIVE, "post": PARENT}), NATIVE)
        self.assertFalse(result["final_result"]["evolution_supported"])
        self.assertLess(result["final_result"]["reserved_validation_success_gain"], 0)


if __name__ == "__main__":
    unittest.main()
