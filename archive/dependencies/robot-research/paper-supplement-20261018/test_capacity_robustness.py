"""Offline semantic, resource-injection, historical reuse and scheduler tests."""
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import capacity_robustness as cr

WORKSPACE = Path(__file__).resolve().parents[2]
SOURCE = WORKSPACE / "RSI/code-twin-casa-v2.2"


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = cr.load_plans(SOURCE)

    def test_finite_balanced_schedule_no_sample_filtering(self):
        jobs = cr.jobs(self.plans)
        self.assertEqual(len(jobs), 480)
        self.assertEqual(len({j["key"] for j in jobs}), 480)
        for setting in cr.SETTINGS:
            for arm in ("native", "memrsi"):
                chosen = [j for j in jobs if j["setting"] == setting and j["arm"] == arm]
                self.assertEqual(len(chosen), 48)
                self.assertEqual({j["plan"]["id"] for j in chosen}, {p["id"] for p in self.plans})
        self.assertEqual({j["setting"] for j in jobs[:10]}, set(cr.SETTINGS))

    def test_all_semantic_variants_leave_private_plan_and_physics_unchanged(self):
        for p in self.plans:
            for setting in cr.SETTINGS:
                new = cr.transform_plan(p, setting)
                original = copy.deepcopy(p)
                for before, after in zip(original["steps"], new["steps"]):
                    if setting in ("paraphrase", "distractor"):
                        self.assertNotEqual(before["text"], after["text"])
                    before["text"] = after["text"]
                self.assertEqual(original, new)

    def test_transform_does_not_consult_expected_answer(self):
        p = self.plans[0]
        changed = copy.deepcopy(p)
        for step in changed["steps"]:
            step["expected"] = "SECRET_ANSWER_CANARY"
            step["checkpoint"] = not step["checkpoint"]
        for setting in cr.SETTINGS:
            a = cr.transform_plan(p, setting)
            b = cr.transform_plan(changed, setting)
            self.assertEqual([s["text"] for s in a["steps"]], [s["text"] for s in b["steps"]])
            self.assertNotIn("SECRET_ANSWER_CANARY", " ".join(s["text"] for s in b["steps"]))

    def test_paraphrase_entities_and_temporal_constraints(self):
        for p in self.plans:
            new = cr.transform_plan(p, "paraphrase")
            text = " ".join(s["text"] for s in new["steps"])
            if p["kind"] == "delayed":
                self.assertIn("do not perform them earlier", text)
                self.assertIn(f"all {p['gap']} upcoming temporary", text)
            if p["kind"] == "revision":
                self.assertIn("supersedes the previous one", text)
            if p["kind"] == "cancellation":
                self.assertIn("no replacement", text)
                self.assertIn("second service remains required", text)
                self.assertIn("first service", text)

    def test_actual_trial_budget_and_public_contract_match_both_arms(self):
        contract = lambda platform: ("Only memory files are writable, together limited to 1024 tokens.", ["finish"])
        engine = types.SimpleNamespace(BUDGET=dict(cr.BASE_BUDGET), contract=contract)
        for setting, cap in (("cap_half", 512), ("base", 1024), ("cap_double", 2048)):
            for arm in ("native", "memrsi"):
                with cr.trial_setting(engine, setting):
                    self.assertEqual(engine.BUDGET["persistent_tokens"], cap)
                    self.assertEqual(engine.BUDGET["active_input_tokens"], 12288)
                    self.assertEqual(engine.BUDGET["output_tokens_per_call"], 2048)
                    self.assertIn(f"limited to {cap} tokens", engine.contract("casa")[0])
                self.assertEqual(engine.BUDGET, cr.BASE_BUDGET)
                self.assertIs(engine.contract, contract)

    def test_unrecognized_contract_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "unrecognized_capacity_contract"):
            cr.capacity_contract(lambda p: ("unrecognized changed API", []), "casa", 512)


class RetryTests(unittest.TestCase):
    def test_capability_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for status in ("decision_failure", "physical_failure", "agent_failure", "success"):
                cr.write(p / "attempt-01/result.json", {"status": status, "logical_calls": 480})
                saved, next_attempt = cr.attempt_state(p)
                self.assertIsNone(next_attempt)
                self.assertEqual(len(saved), 1)

    def test_technical_retries_keep_all_attempts_and_stop_at_three(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for i in range(1, 4):
                cr.write(p / f"attempt-{i:02d}/result.json", {"status": "technical_failure", "error_code": "provider_error", "logical_calls": i})
                saved, nxt = cr.attempt_state(p)
                self.assertEqual(len(saved), i)
                self.assertEqual(nxt, i + 1 if i < 3 else None)
            self.assertEqual(sum(x["row"]["logical_calls"] for x in saved), 6)

    def test_generic_technical_failure_without_evidence_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            cr.write(Path(d) / "attempt-01/result.json", {"status": "technical_failure"})
            with self.assertRaisesRegex(RuntimeError, "unaudited_technical_failure"):
                cr.attempt_state(d)

    def test_interrupted_directory_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "attempt-01").mkdir()
            with self.assertRaisesRegex(RuntimeError, "unfinished_attempt_requires_audit"):
                cr.attempt_state(d)
            self.assertFalse((Path(d) / "attempt-01/result.json").exists())

    def test_active_claim_skip_and_finished_result_skip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            cr.write(p / "jobs.json", [{"key": "base/native/a"}, {"key": "base/memrsi/a"}, {"key": "base/native/b"}])
            cr.write(p / "base/native/a/result.json", {"status": "success"})
            cr.write(p / "claims.json", {"base/memrsi/a": {"identity": cr.identity()}})
            job = cr.claim_job(p, cr.identity(), 6)
            self.assertEqual(job["key"], "base/native/b")
            self.assertEqual(cr.read(p / "claims.json")[job["key"]]["gpu"], 6)

    def test_stale_claim_with_partial_attempt_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            cr.write(p / "jobs.json", [{"key": "base/native/a"}])
            cr.write(p / "claims.json", {"base/native/a": {"identity": {"pid": 999999999, "start_ticks": "1"}}})
            (p / "base/native/a/attempt-01").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "unfinished_attempt_requires_audit"):
                cr.claim_job(p, cr.identity(), 6)

    def test_deadline_must_be_timezone_aware(self):
        self.assertEqual(cr.parse_deadline("2026-10-28T23:59:00+08:00"), cr.parse_deadline("2026-10-28T15:59:00Z"))
        with self.assertRaisesRegex(ValueError, "deadline_requires_timezone"):
            cr.parse_deadline("2026-10-28T23:59:00")

    def test_call_count_fallback_unknown_and_no_double_count(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            cr.write(p / "result.json", {"logical_calls": 23})
            self.assertEqual(cr.attempt_calls(p), (23, "final_logical_calls"))
            cr.write(p / "agent/calls.json", {"calls": 23})
            self.assertEqual(cr.attempt_calls(p), (23, "provider_calls"))
            cr.write(p / "agent/calls.json", {"calls": 24})
            with self.assertRaisesRegex(RuntimeError, "attempt_call_ledger_mismatch"):
                cr.attempt_calls(p)
            (p / "agent/calls.json").unlink()
            (p / "result.json").unlink()
            self.assertIsNone(cr.attempt_calls(p)[0])
            (p / "agent/calls.json").write_text('{"calls":')
            self.assertIsNone(cr.attempt_calls(p)[0])

    def test_gpu_mapping_is_observed_or_explicitly_unknown(self):
        with patch.object(cr.subprocess, "check_output", side_effect=["GPU-6\n", "123, GPU-6\n456, GPU-7\n"]):
            a = cr.gpu_observation(123, 6)
            self.assertTrue(a["actual_mapping_verified"])
            self.assertEqual(a["declared_child_cuda_ordinal"], 0)
        with patch.object(cr.subprocess, "check_output", side_effect=["GPU-6\n", "456, GPU-7\n"]):
            self.assertFalse(cr.gpu_observation(123, 6)["actual_mapping_verified"])
        with patch.object(cr.subprocess, "check_output", side_effect=["GPU-6\n", "123, GPU-7\n"]):
            with self.assertRaisesRegex(RuntimeError, "physical_process_gpu_mismatch"):
                cr.gpu_observation(123, 6)


class BaselineTests(unittest.TestCase):
    def test_reuse_requires_historical_code_manifests_and_all_results(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            base = root / "baseline"
            core_result = root / "core-result/experiment"
            source_stamp = {"files": {"engine": {"run.py": "enginehash"}, "core": {"twenty_agent.py": "corehash"}}}
            plans = [{"id": "one"}]
            cr.write(base / "manifest.json", {"platform": "casa", "plans": plans, "budget": cr.BASE_BUDGET, "methods": ["native", "memrsi"]})
            cr.write(base / "rsi-source.json", {"sha256": "policy", "source": str(core_result)})
            rows = [{"case": "one", "arm": arm, "status": "success"} for arm in ("native", "memrsi")]
            for row in rows:
                cr.write(base / row["arm"] / "one/result.json", row)
            cr.write(base / "rows.json", rows)
            reused, reason = cr.baseline_reuse(base, None, plans, source_stamp, "policy")
            self.assertIsNone(reused)
            self.assertEqual(reason, "historical_source_identity_unproven")
            cr.write(base / "code-manifest.json", source_stamp["files"]["engine"])
            cr.write(core_result.parent / "code-manifest.json", source_stamp["files"]["core"])
            reused, reason = cr.baseline_reuse(base, None, plans, source_stamp, "policy")
            self.assertEqual(len(reused), 2)
            cr.write(base / "memrsi/one/result.json", {"case": "one", "arm": "memrsi", "status": "decision_failure"})
            reused, reason = cr.baseline_reuse(base, None, plans, source_stamp, "policy")
            self.assertIsNone(reused)
            self.assertEqual(reason, "baseline_incomplete_or_unbound")


if __name__ == "__main__":
    unittest.main()
