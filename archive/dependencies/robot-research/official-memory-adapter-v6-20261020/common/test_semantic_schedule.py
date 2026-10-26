import unittest
from dataclasses import FrozenInstanceError

from semantic_schedule import (
    ChunkResult,
    REMEM_SCHEDULE,
    RMB_SCHEDULE,
    Schedule,
    ScheduleContractError,
    run_fixed_chunks,
    validate_session_thresholds,
)


class FixedChunkTests(unittest.TestCase):
    def run_segment(self, callback, command="wash fruit", **kwargs):
        args = dict(schedule=RMB_SCHEDULE, elapsed_steps=0, max_steps=2000)
        args.update(kwargs)
        return run_fixed_chunks(callback, command, **args)

    def test_rmb_holds_identical_command_for_four_chunks(self):
        calls = []
        command = object()
        def execute(actual_command, requested):
            calls.append((actual_command, requested))
            return ChunkResult(requested, {"observation": "unchanged"})
        result = self.run_segment(execute, command)
        self.assertEqual([steps for _, steps in calls], [8, 8, 8, 8])
        self.assertTrue(all(item is command for item, _ in calls))
        self.assertEqual((result.steps_executed, result.end_steps), (32, 32))
        self.assertFalse(result.environment_done)
        self.assertFalse(result.horizon_reached)

    def test_remem_has_one_32_step_chunk(self):
        calls = []
        def execute(command, requested):
            calls.append(requested)
            return ChunkResult(requested, {})
        self.run_segment(execute, schedule=REMEM_SCHEDULE)
        self.assertEqual(calls, [32])

    def test_true_environment_done_stops_without_extra_controls(self):
        calls = []
        def execute(command, requested):
            calls.append(requested)
            return ChunkResult(3, {"observation": "current image"}, environment_done=True)
        result = self.run_segment(execute, elapsed_steps=40)
        self.assertEqual(calls, [8])
        self.assertEqual(result.end_steps, 43)
        self.assertTrue(result.environment_done)

    def test_adapter_horizon_stops_even_before_global_limit(self):
        calls = []
        def execute(command, requested):
            calls.append(requested)
            return ChunkResult(2, {}, horizon_reached=True)
        result = self.run_segment(execute)
        self.assertEqual(calls, [8])
        self.assertTrue(result.horizon_reached)
        self.assertEqual(result.steps_executed, 2)

    def test_remaining_budget_caps_last_chunk_and_sets_horizon(self):
        calls = []
        def execute(command, requested):
            calls.append(requested)
            return ChunkResult(requested, {})
        result = self.run_segment(execute, elapsed_steps=1216, max_steps=1226)
        self.assertEqual(calls, [8, 2])
        self.assertEqual(result.end_steps, 1226)
        self.assertTrue(result.horizon_reached)

    def test_exhausted_budget_never_calls_controller(self):
        def execute(command, requested):
            self.fail("controller called after horizon")
        result = self.run_segment(execute, elapsed_steps=32, max_steps=32)
        self.assertEqual(result.chunk_count, 0)
        self.assertTrue(result.horizon_reached)

    def test_zero_nonterminal_progress_is_technical_error(self):
        calls = []
        def execute(command, requested):
            calls.append(requested)
            return ChunkResult(0, {"observation": "no visible change"})
        with self.assertRaises(ScheduleContractError):
            self.run_segment(execute)
        self.assertEqual(calls, [8])

    def test_zero_terminal_steps_can_exit_without_loop(self):
        result = self.run_segment(lambda command, requested: ChunkResult(0, {}, environment_done=True))
        self.assertEqual((result.steps_executed, result.chunk_count), (0, 1))

    def test_static_image_does_not_stop_real_step_execution(self):
        result = self.run_segment(lambda command, requested: ChunkResult(requested, {"image": "identical"}))
        self.assertEqual((result.chunk_count, result.steps_executed), (4, 32))

    def test_overexecution_is_rejected(self):
        with self.assertRaises(ScheduleContractError):
            self.run_segment(lambda command, requested: ChunkResult(requested + 1, {}))

    def test_invalid_counts_and_flags_are_rejected(self):
        for count in (-1, True, 1.5):
            with self.subTest(count=count), self.assertRaises(ScheduleContractError):
                self.run_segment(lambda command, requested: ChunkResult(count, {}))
        with self.assertRaises(ScheduleContractError):
            self.run_segment(lambda command, requested: ChunkResult(1, {}, environment_done="yes"))

    def test_cumulative_counter_stays_monotonic_across_commands(self):
        execute = lambda command, requested: ChunkResult(requested, {})
        first = self.run_segment(execute, max_steps=50)
        second = self.run_segment(execute, "place fruit", elapsed_steps=first.end_steps, max_steps=50)
        self.assertEqual((first.end_steps, second.start_steps, second.end_steps), (32, 32, 50))

    def test_public_aggregation_does_not_expose_private_terminal_flags(self):
        result = self.run_segment(lambda command, requested: ChunkResult(2, {"visible": ["fruit"]}, environment_done=True))
        public = result.aggregate_public_receipt()
        self.assertEqual(public, {"control_steps": 2, "chunks": [{"visible": ["fruit"]}]})
        public["chunks"][0]["visible"].append("mutated")
        self.assertEqual(result.public_receipts[0]["visible"], ["fruit"])

    def test_schedule_is_frozen_and_validated(self):
        with self.assertRaises(FrozenInstanceError):
            RMB_SCHEDULE.outer_steps = 64
        for chunk, outer in ((0, 32), (8, 0), (8, 4), (8, 30), (True, 32)):
            with self.subTest(chunk=chunk, outer=outer), self.assertRaises(ValueError):
                Schedule(chunk, outer)

    def test_invalid_global_budget_is_rejected(self):
        for elapsed, maximum in ((-1, 32), (33, 32), (0, True)):
            with self.subTest(elapsed=elapsed, maximum=maximum), self.assertRaises(ValueError):
                self.run_segment(lambda command, requested: ChunkResult(requested, {}), elapsed_steps=elapsed, max_steps=maximum)

    def test_session_thresholds_cannot_silently_move_with_outer_frequency(self):
        self.assertEqual(validate_session_thresholds((128, 256), frozen_thresholds=(128, 256)), (128, 256))
        with self.assertRaises(ScheduleContractError):
            validate_session_thresholds((512, 1024), frozen_thresholds=(128, 256))
        with self.assertRaises(ValueError):
            validate_session_thresholds((128, 128), frozen_thresholds=(128, 256))


if __name__ == "__main__":
    unittest.main()
