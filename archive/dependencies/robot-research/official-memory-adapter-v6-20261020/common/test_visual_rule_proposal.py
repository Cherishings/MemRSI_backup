import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import visual_rule_proposal as module
from visual_rule_proposal import (
    MANIFEST_SCHEMA, SNAPSHOT_SCOPE, build_proposal_request, load_development_evidence,
    policy_sha256, validate_and_apply_proposal, validate_parent_policy,
)


def parent_policy():
    return {"schema": 1,
            "guidance": json.dumps({"kind": "procedure_guidance_v2", "procedure":
                "Select relevant evidence fragments. Include the current request and task identity. "
                "Remember that stored observations can be uncertain. Select no more than five source fragments."}),
            "update": json.dumps({"kind": "procedure_update_v2", "procedure":
                "Preserve pending requirements. Keep the identity of distinct requests, changed priorities, "
                "and progress supported by public feedback. Compress irrelevant history while retaining unresolved work."})}


def proposal():
    return {"operator": "update", "anchor": "Preserve pending requirements.",
            "replacement": "Preserve unresolved requirements and the uncertainty of supporting observations.",
            "rationale": "The public observations distinguish claims from established progress.",
            "evidence_case_ids": ["remem-dev-1000"]}


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.parent = parent_policy()
        self.hash = policy_sha256(self.parent)
        self.manifest = {"schema": MANIFEST_SCHEMA, "split": "development",
                         "parent_policy_sha256": self.hash, "cases": []}
        for seed in range(1000, 1012):
            case_id = f"remem-dev-{seed}"
            relative = f"{case_id}/evidence.json"
            self.manifest["cases"].append({"case_id": case_id, "benchmark": "remem",
                "seed": seed, "role": "development", "evidence_file": relative})
            value = {"case_id": case_id, "benchmark": "remem", "seed": seed,
                     "split": "development", "parent_policy_sha256": self.hash,
                     "events": [{"event_id": 1, "observation": {
                         "visible_facts": "An object is visible.",
                         "progress_uncertainty": "Completion is uncertain.",
                         "reference_to_preserve": ""},
                         "public_receipt": "The shared controller executed a bounded action segment."}],
                     "official_success": False}
            path = self.root / relative; path.parent.mkdir()
            path.write_text(json.dumps(value))
        self.path = self.root / "manifest.json"
        self.write_manifest()

    def write_manifest(self):
        self.path.write_text(json.dumps(self.manifest))

    def first_evidence(self):
        return self.root / self.manifest["cases"][0]["evidence_file"]

    def test_builds_one_luna_tool_request_without_calling_a_model(self):
        request = build_proposal_request(self.parent, self.path, self.hash)
        self.assertEqual(request["model"], "gpt-5.6-luna")
        self.assertEqual(request["tool_choice"], "required")
        self.assertEqual(len(request["tools"]), 1)
        schema = request["tools"][0]["function"]["parameters"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(len(schema["properties"]["evidence_case_ids"]["items"]["enum"]), 12)
        data = json.loads(request["messages"][1]["content"])
        self.assertEqual(len(data["development_cases"]), 12)
        self.assertFalse(data["reserved_validation_and_test_access"])
        self.assertTrue(data["observations_are_model_claims_not_oracle_facts"])

    def test_empty_events_need_consistent_official_terminal_status(self):
        path=self.first_evidence();value=json.loads(path.read_text());value['events']=[]
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'empty_events_require_official_terminal_status'):
            load_development_evidence(self.path,self.hash)
        value['terminal_status']='capacity_failure';path.write_text(json.dumps(value))
        result=load_development_evidence(self.path,self.hash)[0]
        self.assertEqual(result['events'],[]);self.assertTrue(result['zero_recorded_valid_actions'])
        self.assertEqual(result['public_initial_request_availability'],'unknown')
        value['official_success']=True;path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'official_terminal_status_inconsistent'):
            load_development_evidence(self.path,self.hash)

    def test_public_predecision_input_is_strict_bounded_and_not_an_action(self):
        path=self.first_evidence();value=json.loads(path.read_text())
        value['events']=[];value['terminal_status']='protocol_failure'
        record={'event_id':1,'public_request':'Actual public request.',
                'memory_before':{'text':'Pending public evidence.','truncated':False},
                'snapshot_scope':'before_decision_not_archive_attribution'}
        value['public_decision_inputs']=[record];path.write_text(json.dumps(value))
        result=load_development_evidence(self.path,self.hash)[0]
        self.assertEqual(result['public_event_count'],0)
        self.assertEqual(result['public_decision_inputs'],[record])
        self.assertEqual(result['pre_decision_memory_availability'],'observed')
        for changed in (dict(record,expected_private='answer'),dict(record,snapshot_scope='oracle'),
                        dict(record,memory_before={'text':'x'*4097,'truncated':False})):
            value['public_decision_inputs']=[changed];path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):load_development_evidence(self.path,self.hash)

    def test_single_operator_exact_local_edit_and_hash(self):
        result = validate_and_apply_proposal(self.parent, proposal(), {"remem-dev-1000"}, self.hash)
        new = result["candidate_policy"]
        self.assertEqual(new["guidance"], self.parent["guidance"])
        self.assertEqual(json.loads(new["update"])["kind"], "procedure_update_v2")
        self.assertIn(proposal()["replacement"], json.loads(new["update"])["procedure"])
        self.assertNotEqual(result["candidate_policy_sha256"], self.hash)
        self.assertEqual(result["candidate_policy_sha256"], policy_sha256(new))
        self.assertFalse(result["adopted"])
        self.assertFalse(result["screen"]["semantic_guarantee"])
        self.assertEqual(self.parent, parent_policy())

    def test_valid_json_response_and_invalid_json_rejected(self):
        result = validate_and_apply_proposal(self.parent, json.dumps(proposal()), {"remem-dev-1000"}, self.hash)
        self.assertFalse(result["adopted"])
        for text in ("not json", '{"operator":"update",}', '{"operator":"update","operator":"guidance"}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_and_apply_proposal(self.parent, text, {"remem-dev-1000"}, self.hash)

    def test_parent_hash_cannot_change_during_proposal(self):
        with self.assertRaisesRegex(ValueError, "parent_policy_hash_mismatch"):
            build_proposal_request(self.parent, self.path, "0" * 64)
        with self.assertRaisesRegex(ValueError, "parent_policy_hash_mismatch"):
            validate_and_apply_proposal(self.parent, proposal(), {"remem-dev-1000"}, "0" * 64)

    def test_anchor_must_be_unique_exact_nonempty_and_local(self):
        values = [dict(proposal(), anchor=""), dict(proposal(), anchor="not found"),
                  dict(proposal(), anchor=json.loads(self.parent["update"])["procedure"])]
        for value in values:
            with self.subTest(anchor=value["anchor"]), self.assertRaises(ValueError):
                validate_and_apply_proposal(self.parent, value, {"remem-dev-1000"}, self.hash)
        parent = copy.deepcopy(self.parent)
        spec = json.loads(parent["update"]); spec["procedure"] += " Preserve pending requirements."
        parent["update"] = json.dumps(spec)
        with self.assertRaisesRegex(ValueError, "proposal_anchor_not_unique"):
            validate_and_apply_proposal(parent, proposal(), {"remem-dev-1000"}, policy_sha256(parent))

    def test_long_replacement_final_procedure_and_unchanged_rejected(self):
        for value in (dict(proposal(), replacement="x" * 1201),
                      dict(proposal(), replacement=proposal()["anchor"])):
            with self.assertRaises(ValueError):
                validate_and_apply_proposal(self.parent, value, {"remem-dev-1000"}, self.hash)
        parent = copy.deepcopy(self.parent)
        parent["update"] = json.dumps({"kind": "procedure_update_v2", "procedure":
                                      proposal()["anchor"] + "x" * 1520})
        value = dict(proposal(), replacement="y" * 200)
        with self.assertRaisesRegex(ValueError, "candidate_procedure_length"):
            validate_and_apply_proposal(parent, value, {"remem-dev-1000"}, policy_sha256(parent))

    def test_heldout_role_or_seed_rejected_before_any_evidence_read(self):
        original = copy.deepcopy(self.manifest)
        for mutate in (lambda m: m["cases"][-1].update(role="validation"),
                       lambda m: m["cases"][-1].update(seed=1100),
                       lambda m: m["cases"][-1].update(seed=1200),
                       lambda m: m.update(split="test")):
            self.manifest = copy.deepcopy(original); mutate(self.manifest); self.write_manifest()
            with patch.object(module, "_read_json", wraps=module._read_json) as reader:
                with self.assertRaises(ValueError):
                    load_development_evidence(self.path, self.hash)
                self.assertEqual(reader.call_count, 1)  # The manifest only.

    def test_missing_or_duplicate_case_prevents_cherry_picked_evidence(self):
        self.manifest["cases"].pop(); self.write_manifest()
        with self.assertRaisesRegex(ValueError, "incomplete_development_manifest"):
            load_development_evidence(self.path, self.hash)
        self.manifest["cases"].append(self.manifest["cases"][0]); self.write_manifest()
        with self.assertRaisesRegex(ValueError, "duplicate_development_case"):
            load_development_evidence(self.path, self.hash)

    def test_arbitrary_files_and_path_escape_cannot_be_read(self):
        original = self.manifest["cases"][0]["evidence_file"]
        for path in ("/tmp/evidence.json", "../evidence.json", "case/raw-log.json", "https://example.com/evidence.json"):
            self.manifest["cases"][0]["evidence_file"] = path; self.write_manifest()
            with self.subTest(path=path), self.assertRaises(ValueError):
                load_development_evidence(self.path, self.hash)
        self.manifest["cases"][0]["evidence_file"] = original; self.write_manifest()
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "evidence.json").write_text("{}")
            self.first_evidence().unlink()
            self.first_evidence().symlink_to(Path(outside) / "evidence.json")
            with self.assertRaisesRegex(ValueError, "development_evidence_path_escape"):
                load_development_evidence(self.path, self.hash)

    def test_raw_oracle_fields_and_image_data_rejected(self):
        path = self.first_evidence(); original = json.loads(path.read_text())
        for key in ("expected_action", "raw_trace", "image_data", "private_state"):
            value = copy.deepcopy(original); value[key] = "private"
            path.write_text(json.dumps(value))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "development_evidence_fields"):
                load_development_evidence(self.path, self.hash)
        value = copy.deepcopy(original); value["events"][0]["reward"] = 1
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "non_public_event_fields"):
            load_development_evidence(self.path, self.hash)

    def test_official_outcome_is_optional_and_boolean_only(self):
        path = self.first_evidence(); value = json.loads(path.read_text())
        value.pop("official_success"); path.write_text(json.dumps(value))
        self.assertNotIn("official_success", load_development_evidence(self.path, self.hash)[0])
        value["official_success"] = "success"; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "official_success_must_be_bool"):
            load_development_evidence(self.path, self.hash)

    def test_public_initial_request_and_actual_action_preserved_exactly(self):
        path = self.first_evidence(); value = json.loads(path.read_text())
        value["public_initial_request"] = "完成眼前交代的工作，然后把物品放回原处。"
        action = {"skill": "execute", "instruction": "Approach the visible object.",
                  "reason": "The current picture does not establish completion."}
        value["events"][0]["public_action"] = action
        path.write_text(json.dumps(value))
        result = load_development_evidence(self.path, self.hash)[0]
        self.assertEqual(result["public_initial_request"], value["public_initial_request"])
        self.assertEqual(result["events"][0]["public_action"], action)
        action["skill"] = "finish"; action["instruction"] = ""
        path.write_text(json.dumps(value))
        self.assertEqual(load_development_evidence(self.path, self.hash)[0]["events"][0]["public_action"]["skill"], "finish")

    def test_public_action_does_not_accept_evaluator_or_hidden_fields(self):
        path = self.first_evidence(); original = json.loads(path.read_text())
        action = {"skill": "execute", "instruction": "Approach the visible object.", "reason": "Continue."}
        for key in ("expected_action", "reward", "task_class", "hidden_environment_id", "state"):
            value = copy.deepcopy(original)
            value["events"][0]["public_action"] = dict(action, **{key: "not public"})
            path.write_text(json.dumps(value))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "non_public_action_fields"):
                load_development_evidence(self.path, self.hash)

    def test_public_request_and_action_lengths_and_contract_enforced(self):
        path = self.first_evidence(); original = json.loads(path.read_text())
        for initial in ({"hidden_class": "private"}, "x" * 1025):
            value = copy.deepcopy(original); value["public_initial_request"] = initial
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "public_initial_request_length"):
                load_development_evidence(self.path, self.hash)
        for action in ({"skill": "execute", "instruction": "", "reason": "x"},
                       {"skill": "finish", "instruction": "move", "reason": "x"},
                       {"skill": "oracle", "instruction": "move", "reason": "x"},
                       {"skill": "execute", "instruction": "x" * 513, "reason": "x"}):
            value = copy.deepcopy(original); value["events"][0]["public_action"] = action
            path.write_text(json.dumps(value))
            with self.subTest(action=action), self.assertRaises(ValueError):
                load_development_evidence(self.path, self.hash)

    def memory_snapshot(self, text="Observed note; correctness is unknown."):
        return {"event_id": 1, "snapshot_scope": SNAPSHOT_SCOPE,
                **{key: {"text": text, "truncated": False}
                   for key in ("memory_before", "memory_after", "guidance_selected")}}

    def test_memory_evidence_is_exact_and_not_called_pure_archive(self):
        path = self.first_evidence(); value = json.loads(path.read_text())
        snapshot = self.memory_snapshot()
        value["memory_evidence"] = [snapshot]; path.write_text(json.dumps(value))
        result = load_development_evidence(self.path, self.hash)[0]
        self.assertEqual(result["memory_evidence"], [snapshot])
        self.assertEqual(result["memory_snapshot_count"], 1)
        self.assertFalse(result["omitted_memory_events_are_unknown"])
        request = build_proposal_request(self.parent, self.path, self.hash)
        self.assertIn("not pure archive transitions", request["messages"][0]["content"])
        self.assertIn("actor writes", request["messages"][0]["content"])

    def test_memory_unknown_fields_or_wrong_scope_rejected(self):
        path = self.first_evidence(); original = json.loads(path.read_text())
        for key in ("expected_private", "hidden_state", "correct_action"):
            value = copy.deepcopy(original)
            value["memory_evidence"] = [dict(self.memory_snapshot(), **{key: "private"})]
            path.write_text(json.dumps(value))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "memory_evidence_fields"):
                load_development_evidence(self.path, self.hash)
        value = copy.deepcopy(original)
        value["memory_evidence"] = [dict(self.memory_snapshot(), snapshot_scope="archive_loss_proven")]
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "memory_snapshot_scope"):
            load_development_evidence(self.path, self.hash)

    def test_memory_fragments_need_explicit_truncation_and_capacity(self):
        path = self.first_evidence(); original = json.loads(path.read_text())
        for fragment in ("raw text", {"text": "x"}, {"text": "x", "truncated": "false"},
                         {"text": "x" * 4097, "truncated": True},
                         {"text": "x", "truncated": False, "expected": "private"}):
            value = copy.deepcopy(original); snapshot = self.memory_snapshot()
            snapshot["memory_before"] = fragment; value["memory_evidence"] = [snapshot]
            path.write_text(json.dumps(value))
            with self.subTest(fragment=fragment), self.assertRaisesRegex(ValueError, "memory_fragment_schema"):
                load_development_evidence(self.path, self.hash)

    def test_memory_excerpt_shortening_is_flagged_and_source_unchanged(self):
        path = self.first_evidence(); value = json.loads(path.read_text())
        value["memory_evidence"] = [self.memory_snapshot("0123456789" * 400)]
        path.write_text(json.dumps(value)); source = path.read_bytes()
        def counter(messages, tools):
            data = json.loads(messages[1]["content"])
            fragment = data["development_cases"][0]["memory_evidence"][0]["memory_before"]
            return 9001 if len(fragment["text"]) > 256 else 4000
        request = build_proposal_request(self.parent, self.path, self.hash, token_counter=counter)
        payload = json.loads(request["messages"][1]["content"])
        fragment = payload["development_cases"][0]["memory_evidence"][0]["memory_before"]
        self.assertEqual(len(fragment["text"]), 256)
        self.assertTrue(fragment["truncated"])
        self.assertEqual(fragment["text"], value["memory_evidence"][0]["memory_before"]["text"][:256])
        self.assertEqual(payload["memory_excerpt_character_cap"], 256)
        self.assertEqual(path.read_bytes(), source)

    def test_first_and_last_events_are_exact_and_omission_is_disclosed(self):
        path = self.first_evidence(); value = json.loads(path.read_text())
        first = value["events"][0]
        middle = copy.deepcopy(first); middle["event_id"] = 2
        last = copy.deepcopy(first); last["event_id"] = 3
        last["observation"]["visible_facts"] = "位置不确定；保留这个原始字符串。"
        value["events"] = [first, middle, last]; path.write_text(json.dumps(value))
        result = load_development_evidence(self.path, self.hash)[0]
        self.assertEqual(result["events"], [first, last])
        self.assertTrue(result["omitted_middle_history_is_unknown"])
        self.assertEqual(result["public_event_count"], 3)

    def test_evidence_hash_and_identity_must_match_manifest(self):
        path = self.first_evidence(); value = json.loads(path.read_text())
        value["parent_policy_sha256"] = "0" * 64; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "evidence_parent_policy_hash_mismatch"):
            load_development_evidence(self.path, self.hash)
        value["parent_policy_sha256"] = self.hash; value["seed"] = 1200
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "development_evidence_identity"):
            load_development_evidence(self.path, self.hash)

    def test_citations_cannot_refer_to_unprovided_cases(self):
        for ids in ([], ["test-1200"], ["remem-dev-1000", "remem-dev-1000"], [1]):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "proposal_evidence_ids"):
                validate_and_apply_proposal(self.parent, dict(proposal(), evidence_case_ids=ids),
                                            {"remem-dev-1000"}, self.hash)

    def test_generated_code_paths_and_private_answers_rejected_heuristically(self):
        replacements = ["Read /data/evaluator/answers.json.", "Use expected_private to finish.",
                        "import os", "exec(command)", "Always finish.", "For cover_blocks choose the target."]
        for text in replacements:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "proposal_heuristic_screen"):
                validate_and_apply_proposal(self.parent, dict(proposal(), replacement=text),
                                            {"remem-dev-1000"}, self.hash)

    def test_measured_request_budget_rejected_before_model_call(self):
        with self.assertRaisesRegex(ValueError, "proposal_input_budget"):
            build_proposal_request(self.parent, self.path, self.hash, token_counter=lambda m, t: 9001)
        self.assertEqual(build_proposal_request(self.parent, self.path, self.hash,
                         token_counter=lambda m, t: 9000)["model"], "gpt-5.6-luna")

    def test_json_kind_and_parent_schema_cannot_be_modified(self):
        parent = copy.deepcopy(self.parent); parent["schema"] = True
        with self.assertRaisesRegex(ValueError, "parent_policy_schema"):
            validate_parent_policy(parent)
        parent = copy.deepcopy(self.parent)
        parent["update"] = '{"kind":"procedure_update_v2","procedure":"x","procedure":"y"}'
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            validate_parent_policy(parent)
        parent["update"] = json.dumps({"kind": "new_action_code", "procedure": "x"})
        with self.assertRaisesRegex(ValueError, "unsupported_parent_operator_kind"):
            validate_parent_policy(parent)


if __name__ == "__main__":
    unittest.main()
