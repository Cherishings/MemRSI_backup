"""Fixed semantic commitments over bounded low-level control chunks.

This module neither chooses commands nor judges visual progress.  The adapter
supplies real executed-step counts and genuine environment termination flags.
Terminal flags are control-flow metadata and are NOT included in the public
receipt returned to an actor.  The adapter remains responsible for ensuring
that each supplied ``public_receipt`` contains only publicly available data.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Tuple


class ScheduleContractError(RuntimeError):
    """A technical adapter/accounting error, not a robot capability failure."""


def _integer(value: int, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class Schedule:
    low_level_steps: int
    outer_steps: int

    def __post_init__(self) -> None:
        _integer(self.low_level_steps, "low_level_steps", minimum=1)
        _integer(self.outer_steps, "outer_steps", minimum=1)
        if self.outer_steps < self.low_level_steps:
            raise ValueError("outer_steps must cover at least one low-level chunk")
        if self.outer_steps % self.low_level_steps:
            raise ValueError("outer_steps must be a multiple of low_level_steps")


# Frozen defaults; changing either is a protocol change for both methods.
RMB_SCHEDULE = Schedule(low_level_steps=8, outer_steps=32)
REMEM_SCHEDULE = Schedule(low_level_steps=32, outer_steps=32)


@dataclass(frozen=True)
class ChunkResult:
    steps_executed: int
    public_receipt: Mapping[str, Any]
    environment_done: bool = False
    horizon_reached: bool = False


@dataclass(frozen=True)
class SegmentResult:
    start_steps: int
    end_steps: int
    chunk_count: int
    public_receipts: Tuple[Mapping[str, Any], ...]
    environment_done: bool
    horizon_reached: bool

    @property
    def steps_executed(self) -> int:
        return self.end_steps - self.start_steps

    def aggregate_public_receipt(self) -> dict:
        """Copy only public chunk receipts and observed control-step counts.

        Do not serialize the entire SegmentResult into the actor's context:
        its terminal flags may originate from a private scoring predicate.
        """
        return {
            "control_steps": self.steps_executed,
            "chunks": [deepcopy(dict(receipt)) for receipt in self.public_receipts],
        }


def run_fixed_chunks(
    execute_chunk: Callable[[Any, int], ChunkResult],
    command: Any,
    *,
    schedule: Schedule,
    elapsed_steps: int,
    max_steps: int,
) -> SegmentResult:
    """Execute one outer segment without changing its committed command.

    ``execute_chunk(command, requested_steps)`` must actually execute at most
    requested_steps controls, return the real step count, and respect the same
    command throughout.  It must check genuine environment termination within
    the chunk rather than execute padded controls after a terminal state.

    The runner never changes a command based on an image, inferred completion,
    or inferred stalling.  It stops at the fixed outer boundary, the physical
    max_steps budget, or a genuine terminal/horizon result from the adapter.
    Returning zero nonterminal steps is a technical error, not a retry signal.
    Positive partial chunks remain bounded by the same physical-step budget.

    elapsed_steps is the episode's cumulative actual count, not a count local
    to a new command.  Callers must carry end_steps forward without resetting
    it when a command, memory state, or chat session changes.
    """
    _integer(elapsed_steps, "elapsed_steps")
    _integer(max_steps, "max_steps")
    if elapsed_steps > max_steps:
        raise ValueError("elapsed_steps exceeds max_steps")
    if not isinstance(schedule, Schedule):
        raise TypeError("schedule must be a Schedule")

    end_steps = elapsed_steps
    segment_end = min(max_steps, elapsed_steps + schedule.outer_steps)
    receipts = []
    environment_done = False
    horizon_reached = end_steps == max_steps
    while end_steps < segment_end:
        requested = min(schedule.low_level_steps, segment_end - end_steps)
        result = execute_chunk(command, requested)
        if not isinstance(result, ChunkResult):
            raise ScheduleContractError("adapter must return ChunkResult")
        if type(result.steps_executed) is not int:
            raise ScheduleContractError("steps_executed must be an integer")
        if result.steps_executed < 0 or result.steps_executed > requested:
            raise ScheduleContractError("adapter executed outside requested step budget")
        if type(result.environment_done) is not bool or type(result.horizon_reached) is not bool:
            raise ScheduleContractError("terminal flags must be boolean")
        if not isinstance(result.public_receipt, Mapping):
            raise ScheduleContractError("public_receipt must be a mapping")
        if not result.steps_executed and not (result.environment_done or result.horizon_reached):
            raise ScheduleContractError("adapter made zero nonterminal control-step progress")

        end_steps += result.steps_executed
        receipts.append(deepcopy(dict(result.public_receipt)))
        environment_done = result.environment_done
        horizon_reached = result.horizon_reached or end_steps == max_steps
        if environment_done or horizon_reached:
            break

    return SegmentResult(
        start_steps=elapsed_steps,
        end_steps=end_steps,
        chunk_count=len(receipts),
        public_receipts=tuple(receipts),
        environment_done=environment_done,
        horizon_reached=horizon_reached,
    )


def validate_session_thresholds(
    thresholds: Tuple[int, ...], *, frozen_thresholds: Tuple[int, ...]
) -> Tuple[int, ...]:
    """Reject silent session-timing changes when control chunking changes.

    Supply cumulative physical-step boundaries, not outer-decision indices.
    This validator does not choose or modify the experiment's thresholds.
    The runner does not itself switch sessions; an adapter must schedule those
    changes explicitly under the predeclared protocol.
    """
    for name, values in (("thresholds", thresholds), ("frozen_thresholds", frozen_thresholds)):
        for value in values:
            _integer(value, name, minimum=1)
        if tuple(values) != tuple(sorted(set(values))):
            raise ValueError(f"{name} must be strictly increasing")
    actual = tuple(thresholds)
    if actual != tuple(frozen_thresholds):
        raise ScheduleContractError("session physical-step thresholds differ from frozen protocol")
    return actual
