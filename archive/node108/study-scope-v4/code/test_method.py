"""Offline behavioral contract checks; no model/network/physical execution."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import method


def policy(g="Use jointly relevant public evidence.", u="Keep public changes and receipts."):
    return {"schema": 1, "guidance": method.guidance_rule(g),
            "update": json.dumps({"kind": "procedure_update_v2", "procedure": u}, sort_keys=True)}


class Provider:
    def __init__(self, response=None, error=None):
        self.requests, self.audit = [], []
        self.error = error
        self.response = response or SimpleNamespace(finish_reason="tool_calls", tool_calls=[
            SimpleNamespace(name="report_advice", arguments={
                "recommendation": "Consider the current authorized request.",
                "basis_ids": ["memory", "current"], "uncertainty": "Check the observed receipt."})])

    async def chat(self, **request):
        self.requests.append(copy.deepcopy(request))
        if self.error:
            raise self.error
        return self.response

    def _append(self, name, record):
        self.audit.append((name, copy.deepcopy(record)))


class BaseAgent:
    def __init__(self, arm, workspace, memory_policy):
        self.arm, self.workspace = arm, Path(workspace)
        self.policy = copy.deepcopy(memory_policy) if memory_policy else {"schema": 1, "guidance": "", "update": ""}
        self.provider = Provider()
        self.provider.memory_policy = self.policy
        self.provider.action_contract = "actor_selected and arbitrary_other are public capabilities."
        self.ops = object() if arm == "memrsi" else None
        self.event_id, self.rollovers, self.received = 0, [], []
        self.writes = {}

    def _write(self, name, value):
        self.writes[name] = value

    async def turn(self, text, facts=None, decision=False):
        self.event_id += 1
        if self.ops is not None and decision:
            await self.ops.guide([], text)
        return {"skill": "actor_selected", "reason": "Actor independent choice."}

    async def observe_only(self, text, facts=None):
        self.event_id += 1
        self.received.append(text)

    async def rollover(self):
        self.rollovers.append("native")


class MethodTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        (self.workspace / "memory").mkdir()
        (self.workspace / "memory/MEMORY.md").write_text("Original public order and relative revision.")
        (self.workspace / "memory/HISTORY.md").write_text("A correlated actual receipt.")
        (self.workspace / "private-evaluator.json").write_text("DO_NOT_READ_PRIVATE_SENTINEL")

    def tearDown(self):
        self.tmp.cleanup()

    async def test_candidate_guidance_text_reaches_request(self):
        p = policy("Candidate G procedure must be used exactly.")
        provider = Provider()
        advisor = method.EvidenceAdvisor(provider, self.workspace, p, "Public API.", "gu_learned")
        await advisor.guide([], "Resume public work.")
        self.assertEqual(provider.requests[0]["messages"][0]["content"], "Candidate G procedure must be used exactly.")
        self.assertEqual(len(provider.requests), 1)
        self.assertTrue(any(name == "guidance-events.jsonl" for name, _ in provider.audit))

    async def test_thinking_has_same_context_schema_model_and_call_count(self):
        parent = policy()
        a, b = Provider(), Provider()
        focused = method.EvidenceAdvisor(a, self.workspace, parent, "Public API.", "gu_parent")
        plain = method.EvidenceAdvisor(b, self.workspace, method.policy_for(parent, parent, "think_u"), "Public API.", "think_u")
        messages = [{"role": "tool", "tool_call_id": "public-link", "content": "Receipt."}]
        await focused.guide(messages, "Continue.")
        await plain.guide(messages, "Continue.")
        first, second = copy.deepcopy(a.requests[0]), copy.deepcopy(b.requests[0])
        self.assertNotEqual(first["messages"][0], second["messages"][0])
        del first["messages"][0]
        del second["messages"][0]
        self.assertEqual(first, second)
        self.assertEqual((len(a.requests), len(b.requests)), (1, 1))

    async def test_private_fields_and_files_are_not_read(self):
        provider = Provider()
        advisor = method.EvidenceAdvisor(provider, self.workspace, policy(), "Public API.", "gu_parent")
        original = Path.read_text
        paths = []
        def tracked(path, *args, **kwargs):
            paths.append(path)
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", tracked):
            await advisor.guide([{"role": "assistant", "content": "Public commitment.",
                "tool_calls": [{"id": "public-link", "type": "function", "function": {"name": "report_action", "arguments": "{}"}}],
                "expected_private": "DO_NOT_READ_PRIVATE_SENTINEL", "reward": 1}], "Continue.")
        self.assertEqual({p.name for p in paths}, {"MEMORY.md", "HISTORY.md"})
        encoded = json.dumps(provider.requests)
        self.assertNotIn("DO_NOT_READ_PRIVATE_SENTINEL", encoded)
        self.assertNotIn("expected_private", encoded)
        self.assertIn("public-link", encoded)

    async def test_invalid_citation_is_retained_without_sampling_retry(self):
        provider = Provider(response=SimpleNamespace(finish_reason="tool_calls", tool_calls=[
            SimpleNamespace(name="report_advice", arguments={"recommendation": "Do work.",
                "basis_ids": ["private_score"], "uncertainty": ""})]))
        advisor = method.EvidenceAdvisor(provider, self.workspace, policy(), "Public API.", "gu_parent")
        with self.assertRaisesRegex(RuntimeError, "guidance_protocol_failure"):
            await advisor.guide([], "Continue.")
        self.assertEqual(len(provider.requests), 1)
        failures = [v for n, v in provider.audit if n == "guidance-advice-failures.jsonl"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["code"], "guidance_advice_invalid_citation")
        self.assertFalse(failures[0]["new_sampling_retry"])

    async def test_call_failure_records_type_without_raw_error_or_retry(self):
        provider = Provider(error=RuntimeError("sensitive-upstream-error-body"))
        advisor = method.EvidenceAdvisor(provider, self.workspace, policy(), "Public API.", "gu_parent")
        with self.assertRaises(RuntimeError):
            await advisor.guide([], "Continue.")
        self.assertEqual(len(provider.requests), 1)
        self.assertNotIn("sensitive-upstream-error-body", json.dumps(provider.audit))
        self.assertTrue(any(n == "guidance-advice-failures.jsonl" for n, _ in provider.audit))

    async def test_guidance_off_and_native_archive_boundaries_preserved(self):
        parent = policy()
        for arm in ("native", "u_only"):
            effective = method.policy_for(parent, parent, arm)
            bound = method.bind_agent_class(BaseAgent, arm, effective)
            self.assertIs(bound.rollover, BaseAgent.rollover)
            agent = bound("native" if arm == "native" else "memrsi", self.workspace, effective)
            self.assertIsNone(agent.ops)
            await agent.turn("Continue.", decision=True)
            for _ in range(19):
                await agent.rollover()
            self.assertEqual(agent.provider.requests, [])
            self.assertEqual(len(agent.rollovers), 19)

    async def test_actor_independence_and_failure_receipt_correlation_all_arms(self):
        parent = policy()
        for arm in method.ARMS:
            effective = method.policy_for(parent, parent, arm)
            bound = method.bind_agent_class(BaseAgent, arm, effective)
            agent = bound("native" if arm == "native" else "memrsi", self.workspace, effective)
            decision = await agent.turn("Continue.", decision=True)
            self.assertEqual(decision["skill"], "actor_selected")
            text = 'Execution feedback: {"skill":"actor_selected","success":false,"native_task_complete":false}'
            await agent.observe_only(text, {"expected_private": "never-used"})
            self.assertTrue(agent.received[-1].startswith(text + "\n"))
            association = json.loads(agent.received[-1].split("(dispatcher metadata): ", 1)[1])
            self.assertEqual(association, {"decision_event": 1, "submitted_skill": "actor_selected"})
            self.assertIsNone(agent.pending_dispatch)
            self.assertNotIn("never-used", json.dumps(agent.provider.requests))

    def test_ablations_and_learning_swaps(self):
        parent, learned = policy("parent G", "parent U"), policy("learned G", "learned U")
        g, u = method.policy_for(parent, learned, "g_only"), method.policy_for(parent, learned, "u_only")
        self.assertEqual((g["guidance"], g["update"]), (learned["guidance"], ""))
        self.assertEqual((u["guidance"], u["update"]), ("", learned["update"]))
        rg, ru = method.policy_for(parent, learned, "rsi_g_only"), method.policy_for(parent, learned, "rsi_u_only")
        self.assertEqual(rg, dict(parent, guidance=learned["guidance"]))
        self.assertEqual(ru, dict(parent, update=learned["update"]))
        self.assertEqual(method.policy_for(parent, learned, "gu_parent"), parent)
        self.assertEqual(method.policy_for(parent, learned, "gu_learned"), learned)

    async def test_physical_recorded_receipt_replays_idempotently(self):
        bound = method.bind_agent_class(BaseAgent, "gu_parent", policy())
        physical = bound("memrsi", self.workspace, policy())
        await physical.turn("Choose one action.", decision=True)
        raw = 'Execution feedback: {"skill":"actor_selected","segment_success":false,"native_task_complete":false}'
        await physical.observe_only(raw)
        recorded = physical.received[-1]
        replay = bound("memrsi", self.workspace, policy())
        await replay.turn("Choose one action.", decision=True)
        await replay.observe_only(recorded)
        self.assertEqual(replay.received, [recorded])
        self.assertEqual(recorded.count("Execution correlation (dispatcher metadata):"), 1)
        self.assertIsNone(replay.pending_dispatch)
        audit = [v for n, v in replay.provider.audit if n == "receipt-correlations.jsonl"]
        self.assertEqual(len(audit), 1)
        self.assertTrue(audit[0]["recorded_association_reused"])
        # Historical teacher-forced receipts remain unchanged without a new action.
        self.assertEqual(method.correlate_receipt(recorded, None), (recorded, False))

    async def test_recorded_receipt_mismatch_is_protocol_failure_and_not_delivered(self):
        bound = method.bind_agent_class(BaseAgent, "gu_parent", policy())
        for invalid in (
            'Execution feedback: {"skill":"actor_selected","segment_success":true}\nExecution correlation (dispatcher metadata): {"decision_event":2,"submitted_skill":"actor_selected"}',
            'Execution feedback: {"skill":"wrong_action","segment_success":true}\nExecution correlation (dispatcher metadata): {"decision_event":1,"submitted_skill":"actor_selected"}',
        ):
            replay = bound("memrsi", self.workspace, policy())
            await replay.turn("Choose one action.", decision=True)
            with self.assertRaisesRegex(RuntimeError, "action_protocol_failure"):
                await replay.observe_only(invalid)
            self.assertEqual(replay.received, [])
            self.assertIsNotNone(replay.pending_dispatch)
            audits = [v for n, v in replay.provider.audit if n == "receipt-correlation-failures.jsonl"]
            self.assertEqual(audits[0]["code"], "receipt_correlation_mismatch")


if __name__ == "__main__":
    unittest.main()
