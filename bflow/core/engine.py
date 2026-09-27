"""Fixed-step engine that runs without a server and without real-time waits."""

from collections import deque
from random import Random

from bflow.core.events import EventLog, Severity
from bflow.core.layout import LayoutConfig, minimal_layout
from bflow.core.models import Baggage, Conveyor
from bflow.core.stats import Stats


STEP_MS = 50
STEP_SECONDS = STEP_MS / 1000


class Engine:
    """Owns the layout, state and random generator of a single run.

    The tick counts completed steps: the initial state is at tick 0, time 0.
    Each call to step() completes exactly 50 simulated ms. The caller decides
    when to run it: pause and real-time speed do not change the step.
    Time is derived from the integer tick, avoiding errors from repeatedly
    adding 0.05.

    All random draws in the engine use rng, never the global generator of the
    random module: the same seed and the same operations reproduce the run
    with no interference between instances. Without a layout the engine runs
    the one-belt minimal route.
    """

    def __init__(self, layout: LayoutConfig | None = None, *, seed: int = 42) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        self.layout = layout if layout is not None else minimal_layout()
        self.seed = seed
        self.rng = Random(seed)
        self._tick = 0
        # One state per belt, in layout order.
        self.conveyors = {belt.id: Conveyor(belt) for belt in self.layout.belts}
        # Belt fed by each input: the layout guarantees exactly one.
        self.input_conveyors = {belt.source_id: self.conveyors[belt.id]
                                for belt in self.layout.belts
                                if belt.source_id in {node.id for node in self.layout.inputs}}
        self._output_ids = [node.id for node in self.layout.outputs]
        # Bags generated but not yet admitted, per input, oldest first.
        self.waiting: dict[str, deque[Baggage]] = {node.id: deque() for node in self.layout.inputs}
        self.generated_count = 0
        self.generated_by_input = {node.id: 0 for node in self.layout.inputs}
        self.admitted_count = 0
        self.correctly_delivered_count = 0
        self.misdelivered_count = 0
        self._total_travel_time_s = 0.0
        # Only the exits of the last tick: no unbounded history.
        self.exited_this_tick: tuple[Baggage, ...] = ()
        self.events = EventLog()
        self._entrance_queued = {node.id: False for node in self.layout.inputs}

    @property
    def tick(self) -> int:
        """Number of completed steps, initially zero."""
        return self._tick

    @property
    def time_s(self) -> float:
        """Simulated time in seconds, computed without accumulating rounding errors."""
        return self._tick * STEP_MS / 1000

    @property
    def waiting_count(self) -> int:
        """Bags waiting at all the inputs."""
        return sum(len(queue) for queue in self.waiting.values())

    @property
    def exited_count(self) -> int:
        """All exits, correct and wrong, without a duplicate counter."""
        return self.correctly_delivered_count + self.misdelivered_count

    @property
    def in_transit_count(self) -> int:
        """Bags on any belt, including stopped ones; waiting bags excluded."""
        return sum(len(conveyor.baggage) for conveyor in self.conveyors.values())

    @property
    def mean_travel_time_s(self) -> float | None:
        """Mean admission → exit time, wrong exits included; None without samples.

        CLI and GUI display None as "—". Only the sum of the times is kept,
        not a growing history of exited bags.
        """
        if self.exited_count == 0:
            return None
        return self._total_travel_time_s / self.exited_count

    def stats(self) -> Stats:
        """Snapshot of the counters at the current tick, for the CLI and GUI."""
        return Stats(
            tick=self.tick,
            time_s=self.time_s,
            generated=self.generated_count,
            waiting=self.waiting_count,
            admitted=self.admitted_count,
            correctly_delivered=self.correctly_delivered_count,
            misdelivered=self.misdelivered_count,
            in_transit=self.in_transit_count,
            mean_travel_time_s=self.mean_travel_time_s,
            errors=self.events.counts[Severity.ERROR],
            warnings=self.events.counts[Severity.WARNING],
        )

    def step(self) -> None:
        """Completes one fixed step without reading real time or waiting."""
        self._tick += 1
        self._move()
        leaving = self._evaluate_transfers()
        self._apply_transfers(leaving)
        self._generate()
        self._admit()
        self._update_entrance_queues()

    def _move(self) -> None:
        """Advances each belt from the exit towards the entrance.

        On each belt the front edge stops at the end of the belt or at the
        minimum gap from the rear edge of the bag ahead, using its updated
        position. Ready bags are moved to the next element only after every
        bag has finished moving.
        """
        for conveyor in self.conveyors.values():
            distance = conveyor.config.speed_m_s * STEP_SECONDS
            front_limit = conveyor.config.length_m
            for baggage in reversed(conveyor.baggage):
                max_position = front_limit - baggage.length_m
                # max prevents tiny backward moves caused by rounding of the gap.
                baggage.position_m = max(
                    baggage.position_m,
                    min(baggage.position_m + distance, max_position),
                )
                front_limit = baggage.position_m - self.layout.min_gap_m

    def _has_entry_space(self, conveyor: Conveyor, baggage: Baggage) -> bool:
        """True if the bag fits at position zero, keeping the gap to the nearest bag."""
        if not conveyor.baggage:
            return True
        return conveyor.baggage[0].position_m >= baggage.length_m + self.layout.min_gap_m

    def _evaluate_transfers(self) -> tuple[Conveyor, ...]:
        """Returns the belts whose front bag leaves this tick, without mutating state.

        A bag leaves when its front edge is at the end of the belt. The limit
        uses the same subtraction as movement, avoiding inconsistent
        comparisons due to rounding; no epsilon brings the exit forward.
        An output always accepts the bag. A following belt accepts it only if
        its entrance has space: a belt fed by another belt has no other
        source, so there are no conflicts. Belts that end at a merge or a
        sorter keep their bags for now.
        """
        leaving = []
        for conveyor in self.conveyors.values():
            if not conveyor.baggage:
                continue
            baggage = conveyor.baggage[-1]
            if baggage.position_m < conveyor.config.length_m - baggage.length_m:
                continue
            target_id = conveyor.config.target_id
            if target_id in self._output_ids:
                leaving.append(conveyor)
            elif target_id in self.conveyors:
                if self._has_entry_space(self.conveyors[target_id], baggage):
                    leaving.append(conveyor)
        return tuple(leaving)

    def _apply_transfers(self, leaving: tuple[Conveyor, ...]) -> None:
        """Moves the front bag of each selected belt, exactly once.

        On a following belt the bag starts at position zero, like a newly
        admitted bag; an output unloads it automatically. Movement is not
        repeated after the transfer: following bags use the freed space, and
        the transferred bag moves, from the next tick.
        """
        exited = []
        for conveyor in leaving:
            baggage = conveyor.baggage.pop()
            target_id = conveyor.config.target_id
            if target_id in self.conveyors:
                baggage.conveyor_id = target_id
                baggage.position_m = 0.0
                self.conveyors[target_id].baggage.insert(0, baggage)
            else:
                self._exit(baggage, target_id)
                exited.append(baggage)
        self.exited_this_tick = tuple(exited)

    def _exit(self, baggage: Baggage, output_id: str) -> None:
        """Removes the bag from the plant at an output and classifies the arrival."""
        if baggage.entered_at_s is None:
            raise ValueError("An exiting bag must have been admitted")
        baggage.conveyor_id = None
        baggage.exited_at_s = self.time_s
        if baggage.destination_id == output_id:
            self.correctly_delivered_count += 1
        else:
            self.misdelivered_count += 1
        self._total_travel_time_s += self.time_s - baggage.entered_at_s

    def _generate(self) -> None:
        """Queues every due arrival at each input, without losing demand when it is full.

        Inputs are visited in layout order, so bag numbers are reproducible.
        The total of each input is derived from elapsed time, without rounding
        an interval to ticks or accumulating fractions at every step. The
        first arrival happens after a full interval. The timestamp is that of
        the tick in which the arrival is detected (a delay shorter than one
        step). The destination is any output, drawn with equal probability.
        """
        for node in self.layout.inputs:
            due_count = int(self.tick * STEP_MS * node.arrival_rate_bags_s / 1000)
            while self.generated_by_input[node.id] < due_count:
                self.generated_by_input[node.id] += 1
                self.generated_count += 1
                self.waiting[node.id].append(Baggage(
                    id=f"bag-{self.generated_count}",
                    destination_id=self.rng.choice(self._output_ids),
                    length_m=self.layout.baggage_length_m,
                    generated_at_s=self.time_s,
                ))

    def _admit(self) -> None:
        """Admits the first waiting bag of each input whose belt entrance is free.

        The belt list is ordered from entrance to exit: the first element is
        the closest to the new bag. One admission per tick is enough because
        the new bag immediately occupies position zero.
        """
        for input_id, queue in self.waiting.items():
            conveyor = self.input_conveyors[input_id]
            if not queue or not self._has_entry_space(conveyor, queue[0]):
                continue
            baggage = queue.popleft()
            baggage.conveyor_id = conveyor.config.id
            baggage.entered_at_s = self.time_s
            baggage.position_m = 0.0
            conveyor.baggage.insert(0, baggage)
            self.admitted_count += 1

    def _update_entrance_queues(self) -> None:
        """Records the start and end of each input's queue, not every waiting tick.

        A queue exists when at least one bag is still waiting after admission.
        It is an informational event: the prolonged-wait warning will have
        its own thresholds.
        """
        for input_id, queue in self.waiting.items():
            queued = bool(queue)
            if queued == self._entrance_queued[input_id]:
                continue
            self._entrance_queued[input_id] = queued
            if queued:
                kind, message = "entrance_queue_started", "Entrance queue: no space on the belt"
            else:
                kind, message = "entrance_queue_cleared", "Entrance queue cleared"
            self.events.record(self.tick, self.time_s, Severity.INFO, kind, message,
                               element_id=input_id)
