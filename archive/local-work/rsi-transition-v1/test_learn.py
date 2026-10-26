"""Offline selection/integrity tests only: no runtime import, network, or GPU."""
import copy
import ast
from contextlib import asynccontextmanager
from contextvars import ContextVar
import json
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pathlib import Path
import learn


def policy():
    return {"schema": 1,
            "guidance": json.dumps({"kind": "procedure_guidance_v2", "procedure": "Use public evidence. " * 12}),
            "update": json.dumps({"kind": "procedure_update_v2", "procedure": "Preserve verified status. " * 12})}


def row(arm, sid, rep, correct, status="completed", calls=10, planned=3):
    return {"arm": arm, "source_id": sid, "repeat": rep, "correct": correct,
            "answered": correct, "planned": planned, "status": status, "logical_calls": calls}


class LearningTests(unittest.TestCase):
    def test_one_operator_only_and_joint_composition(self):
        parent = policy()
        g = learn.apply_edit(parent, {"target": "guidance", "replacement": "Abstain when unsupported.", "rationale": "Ground advice."}, "guidance")
        u = learn.apply_edit(parent, {"target": "update", "replacement": "Retain uncertainty.", "rationale": "Do not overwrite evidence."}, "update")
        self.assertEqual(g["update"], parent["update"])
        self.assertEqual(u["guidance"], parent["guidance"])
        combos = learn.make_combinations(parent, {"guidance": g, "update": u})
        self.assertEqual(list(combos), list(learn.ARMS))
        self.assertEqual(combos["joint"]["guidance"], g["guidance"])
        self.assertEqual(combos["joint"]["update"], u["update"])

    def test_invalid_edits_not_promoted(self):
        p = policy()
        for patch in ({"target": "update", "replacement": "A", "rationale": "B"},
                      {"target": "guidance", "anchor": "Use public evidence.", "replacement": "A", "rationale": "B"},
                      {"target": "guidance", "replacement": "serve_A", "rationale": "B"},
                      {"target": "guidance", "replacement": "x" * 1201, "rationale": "B"}):
            with self.assertRaises(ValueError):
                learn.apply_edit(p, patch, "guidance")
        self.assertEqual(list(learn.make_combinations(p, {})), ["parent"])

    def test_source_stratification_is_fixed_not_best_of(self):
        rows = [{"id": str(i), "status": "success" if i % 2 else "decision_failure"} for i in range(8)]
        self.assertEqual([r["id"] for r in learn.select_sources(list(reversed(rows)))], ["0", "2", "1", "3"])

    def test_validation_selects_distinct_histories_without_result_preference(self):
        rows = [{"id": key, "history": history, "status": status} for key, history, status in
                [("01", "A", "decision_failure"), ("02", "A", "success"),
                 ("03", "B", "decision_failure"), ("04", "B", "success")]]
        self.assertEqual([r["id"] for r in learn.select_validation(rows)], ["01", "03"])

    def test_positive_gain_and_validation_nondecrease(self):
        rows = [row("parent", "a", 0, 2, "decision_failure"), row("g_only_edit", "a", 0, 3)]
        self.assertTrue(learn.score_pair(rows, "g_only_edit", 1)["passed"])
        rows[0] = row("parent", "a", 0, 3)
        self.assertFalse(learn.score_pair(rows, "g_only_edit", 1)["passed"])
        self.assertTrue(learn.score_pair(rows, "g_only_edit", 1, validation=True)["passed"])

    def test_persistent_regression_is_rejected_despite_aggregate_gain(self):
        rows = []
        for rep in range(2):
            rows += [row("parent", "a", rep, 3), row("joint", "a", rep, 2, "decision_failure"),
                     row("parent", "b", rep, 0, "decision_failure"), row("joint", "b", rep, 3)]
        score = learn.score_pair(rows, "joint", 4)
        self.assertEqual(score["correct_gain"], 4)
        self.assertEqual(score["persistent_regressions"], ["a"])
        self.assertFalse(score["passed"])

    def test_method_failures_count_and_technical_failures_invalidate(self):
        rows = [row("parent", "a", 0, 0, "agent_failure"), row("u_only_edit", "a", 0, 3)]
        self.assertTrue(learn.score_pair(rows, "u_only_edit", 1)["passed"])
        rows[0]["status"] = "technical_failure"
        self.assertEqual(learn.score_pair(rows, "u_only_edit", 1)["valid_pairs"], 0)

    def test_no_denominator_changes_or_duplicate_pairs(self):
        rows = [row("parent", "a", 0, 2), row("joint", "a", 0, 3, planned=4)]
        with self.assertRaises(ValueError):
            learn.score_pair(rows, "joint", 1)
        rows[1]["planned"] = 3
        with self.assertRaises(ValueError):
            learn.score_pair(rows + [rows[1]], "joint", 1)

    def test_corrected_source_not_full_completion_and_cost_gate(self):
        rows = [row("parent", "a", 0, 1, "decision_failure"), row("joint", "a", 0, 2, "source_error_corrected", 16)]
        score = learn.score_pair(rows, "joint", 1)
        self.assertEqual(score["completed"]["joint"], 0)
        self.assertFalse(score["cost_ok"])
        self.assertFalse(score["passed"])

    def test_selection_prefers_training_gain_then_fewer_edits_then_cost(self):
        train = {arm: {"passed": True, "correct_gain": gain, "logical_calls": {arm: cost}}
                 for arm, gain, cost in [("g_only_edit", 2, 20), ("u_only_edit", 3, 30), ("joint", 10, 40)]}
        val = {arm: {"passed": True, "logical_calls": {arm: 10}} for arm in train}
        self.assertEqual(learn.choose_candidate(train, val), "joint")
        train["joint"]["correct_gain"] = 3
        self.assertEqual(learn.choose_candidate(train, val), "u_only_edit")
        val["u_only_edit"]["passed"] = False
        train["joint"]["correct_gain"] = 2
        self.assertEqual(learn.choose_candidate(train, val), "g_only_edit")
        for arm in val:
            val[arm]["passed"] = False
        self.assertIsNone(learn.choose_candidate(train, val))

    def test_inputs_cannot_change_on_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "registration.json"
            learn.freeze_json(path, {"hash": "one"})
            learn.freeze_json(path, {"hash": "one"})
            with self.assertRaises(RuntimeError):
                learn.freeze_json(path, {"hash": "two"})

    def test_strict_critic_types_and_single_submit(self):
        value = {"generic": True, "no_task_answers": True, "preserves_user_authority": True,
                 "preserves_advisor_interface": True, "rationale": "Acceptable."}
        response = {"finish_reason": "tool_calls", "tool_calls": [{"name": "submit", "arguments": value}]}
        self.assertEqual(learn.validate_submission(response, learn.CRITIC_SCHEMA), value)
        bad = copy.deepcopy(response); bad["tool_calls"][0]["arguments"]["generic"] = "true"
        with self.assertRaises(ValueError):
            learn.validate_submission(bad, learn.CRITIC_SCHEMA)
        response["tool_calls"] *= 2
        with self.assertRaises(ValueError):
            learn.validate_submission(response, learn.CRITIC_SCHEMA)

    def test_truncation_explicit_not_absence_evidence(self):
        clipped = learn.compact("a" * 1000, 100)
        self.assertTrue(clipped["truncated"])
        self.assertEqual(clipped["original_characters"], 1000)
        self.assertIn("OMITTED", clipped["text"])


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        probe_patch = patch("network_wait.probe", return_value=True)
        probe_patch.start(); self.addCleanup(probe_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reservations = []
        outer = self
        class FakeProvider:
            async def chat(self, **kwargs):
                return await self._chat_attempts(**kwargs)

            async def _chat_attempts(self, **kwargs):
                return await self._chat_attempts_locked(**kwargs)

            async def _chat_attempts_locked(self, **kwargs):
                raise AssertionError("unpatched transport")

            def __init__(self):
                self.calls = self.wire_attempts = self.format_repairs = 0
                self.output = Path(outer.temp.name)
                self.default_model = "offline-test"
                self.last_transport_error = {}
                self.error = None
                self.logs = []

            @staticmethod
            def _sanitize_empty_content(messages):
                return messages

            @asynccontextmanager
            async def _request_lease(self):
                yield

            async def _complete(self, request):
                if self.error:
                    self.last_transport_error = {"code": self.error, "http_status": 429}
                return SimpleNamespace(finish_reason="error" if self.error else "stop")

            def _append(self, name, record):
                self.logs.append((name, record))
        self.base = FakeProvider
        self.module = SimpleNamespace(Provider=FakeProvider, OUTPUT_CAP=2048, CALL_LIMIT=480,
            reserve_learning_call=lambda: self.reservations.append(True), LEARNING_LEDGER=ContextVar("offline_ledger", default=None))
        old_path = sys.path[:]
        with patch.object(learn.importlib, "import_module", return_value=self.module):
            learn.install_runtime(self.temp.name, self.temp.name)
        sys.path[:] = old_path

    async def test_real_budget_override_still_precedes_transport(self):
        source = Path(os.environ.get("PAOS_LEARN_TEST_SOURCE",
            "/home/edy/Documents/Codex/2026-10-01/new-chat/work/emergency-migration-20261022/from-a100/paos-tree/worktrees/memrsi-bounded-v2_2"))
        if not (source / "twenty_agent.py").exists():
            self.skipTest("set PAOS_LEARN_TEST_SOURCE to the frozen runtime source")
        # Execute the existing runtime's actual guard, without importing any
        # model client or PAOS dependencies, against the patched transport.
        tree = ast.parse((source / "twenty_agent.py").read_text())
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BudgetProvider")
        namespace = {"ProcedureProvider": self.base, "request_tokens": lambda messages, tools: len(messages)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source / "twenty_agent.py"), "exec"), namespace)
        provider = namespace["BudgetProvider"]()
        provider.budget = {"active_input_tokens": 1}
        with self.assertRaisesRegex(RuntimeError, "active_context_budget_exceeded"):
            await provider.chat(messages=[{}, {}])
        self.assertEqual(provider.calls, 0)
        self.assertEqual(self.reservations, [])
        await provider.chat(messages=[{}])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.wire_attempts, 1)
        self.assertEqual(len(self.reservations), 1)

    async def test_generation_limit_is_method_failure_and_quota_is_infrastructure(self):
        for error, expected in [("generation_output_limit", "generation_output_limit"),
                                ("rate_limit_exceeded", "provider_error")]:
            provider = self.base(); provider.error = error
            with self.assertRaisesRegex(RuntimeError, expected):
                await provider.chat(messages=[{"role": "user", "content": "offline"}])
            self.assertEqual(provider.wire_attempts, 1)
            self.assertEqual(provider.calls, 1)

    def args(self):
        root = Path(self.temp.name)
        for name, value in [("parent.json", policy()), ("train.json", []),
                            ("validation.json", []), ("budget.json", {"active_input_tokens": 12288})]:
            learn.write(root / name, value)
        return SimpleNamespace(root=str(root), source=str(root), core=str(root),
            parent_policy=str(root / "parent.json"), train_manifest=str(root / "train.json"),
            validation_manifest=str(root / "validation.json"), budget=str(root / "budget.json"))

    async def test_no_eligible_sources_freezes_parent_without_model_call(self):
        args = self.args()
        with patch.object(learn, "install_runtime", return_value=self.module), \
             patch.object(learn, "inspect_sources", return_value=([], {"eligible": []})), \
             patch.object(learn, "single_structured", side_effect=AssertionError("no model expected")):
            result = await learn.learn(args)
        self.assertFalse(result["accepted"])
        self.assertEqual(learn.read(Path(args.root) / "learning/selected-policy.json"), policy())
        self.assertEqual(result["ledger"]["calls"], 0)

    async def test_infrastructure_failure_exits_without_selection(self):
        args = self.args()
        with patch.object(learn, "install_runtime", return_value=self.module), \
             patch.object(learn, "inspect_sources", side_effect=RuntimeError("development_infrastructure_failure")):
            with self.assertRaisesRegex(RuntimeError, "development_infrastructure_failure"):
                await learn.learn(args)
        self.assertFalse((Path(args.root) / "learning/selected-policy.json").exists())
        self.assertTrue((Path(args.root) / "learning/blocked.json").exists())


if __name__ == "__main__":
    unittest.main()
