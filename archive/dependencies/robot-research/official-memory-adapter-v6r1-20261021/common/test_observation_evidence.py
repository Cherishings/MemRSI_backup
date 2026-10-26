import json
import unittest

from observation_evidence import (
    FIELDS, MAX_FIELD_CHARS, MAX_OBSERVATION_CHARS, OBSERVATION_SCHEMA,
    render_observation, validate_observation,
)


class ObservationEvidenceTests(unittest.TestCase):
    def notes(self, **changes):
        return dict(visible_facts="An object is visible near the gripper.",
                    progress_uncertainty="Contact is occluded; completion is unknown.",
                    reference_to_preserve="", **changes)

    def test_exact_schema_has_no_evaluator_or_world_state_fields(self):
        self.assertEqual(set(OBSERVATION_SCHEMA["properties"]), set(FIELDS))
        self.assertEqual(set(OBSERVATION_SCHEMA["required"]), set(FIELDS))
        self.assertFalse(OBSERVATION_SCHEMA["additionalProperties"])
        self.assertTrue(all(p["maxLength"] == 256
                            for p in OBSERVATION_SCHEMA["properties"].values()))
        value = self.notes()
        for extra in ("success", "reward", "expected_action", "env_state", "ground_truth"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "observation_fields"):
                validate_observation(dict(value, **{extra: True}))

    def test_missing_fields_and_wrong_types_rejected(self):
        for value in (None, [], "notes", {}, {"visible_facts": "visible"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_observation(value)
        for key in FIELDS:
            value = self.notes(); value[key] = ["a claim"]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "observation_field_type"):
                validate_observation(value)

    def test_capacity_boundary_does_not_truncate_or_silently_rewrite(self):
        value = {key: "x" * MAX_FIELD_CHARS for key in FIELDS}
        self.assertEqual(sum(map(len, value.values())), MAX_OBSERVATION_CHARS)
        self.assertEqual(validate_observation(value), value)
        for key in FIELDS:
            too_long = dict(value); too_long[key] += "x"
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "observation_field_capacity"):
                validate_observation(too_long)

    def test_empty_and_unicode_notes_remain_exact(self):
        value = {key: "" for key in FIELDS}
        value["reference_to_preserve"] = "盘子左侧；是否接触不确定。\n这是模型观察。"
        rendered = render_observation(3, value)
        record = json.loads(rendered.split("\n", 1)[1])
        self.assertEqual(record["observation"], value)
        self.assertIn("盘子左侧", rendered)

    def test_success_claim_is_labelled_unverified_not_promoted_to_receipt(self):
        value = dict(visible_facts="Everything is completed.",
                     progress_uncertainty="", reference_to_preserve="")
        text = render_observation(4, value)
        self.assertIn("not an execution receipt or confirmation of task success", text)
        record = json.loads(text.split("\n", 1)[1])
        self.assertFalse(record["verified_by_environment"])
        self.assertEqual(record["source"], "actor_generated_from_current_public_observation")
        self.assertEqual(record["timing"], "before_requested_action_execution")
        self.assertEqual(record["observation"]["visible_facts"], "Everything is completed.")
        self.assertNotIn("success", record)
        self.assertNotIn("status", record)

    def test_event_id_is_positive_integer_not_boolean(self):
        for invalid in (True, False, 0, -1, 1.0, "1", None):
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, "observation_event_id"):
                render_observation(invalid, self.notes())
        record = json.loads(render_observation(7, self.notes()).split("\n", 1)[1])
        self.assertEqual(record["event"], 7)
        self.assertEqual(record["public_observation_ref"], "Event 7")

    def test_stable_serialization_and_detached_copy(self):
        value = self.notes()
        reversed_value = dict(reversed(list(value.items())))
        self.assertEqual(render_observation(2, value), render_observation(2, reversed_value))
        validated = validate_observation(value)
        value["visible_facts"] = "changed"
        self.assertNotEqual(validated["visible_facts"], value["visible_facts"])

    def test_notes_do_not_carry_implicit_cross_event_state(self):
        first = dict(visible_facts="Location A.", progress_uncertainty="",
                     reference_to_preserve="First observed location A.")
        second = dict(visible_facts="Location B.", progress_uncertainty="",
                      reference_to_preserve="")
        render_observation(1, first)
        later = json.loads(render_observation(2, second).split("\n", 1)[1])
        self.assertEqual(later["observation"], second)
        self.assertNotIn("Location A", json.dumps(later))


if __name__ == "__main__":
    unittest.main()
