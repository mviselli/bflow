"""Fixed-step engine that runs without a server and without real-time waits."""

from collections import deque
from random import Random

from bflow.core.events import EventLog, Severity
from bflow.core.models import Baggage, Conveyor, SimulationConfig
from bflow.core.stats import Stats


STEP_MS = 50
STEP_SECONDS = STEP_MS / 1000


class Engine:
    """Owns the configuration, state and random generator of a single run.

    The tick counts completed steps: the initial state is at tick 0, time 0.
    Each call to step() completes exactly 50 simulated ms. The caller decides
    when to run it: pause and real-time speed do not change the step.
    Time is derived from the integer tick, avoiding errors from repeatedly
    adding 0.05.

    All future random draws in the engine must use rng, never the global
    generator of the random module. The same seed and the same operations
    reproduce the sequence with no interference between instances. Arrivals
    are regular, at the configured rate, and detected at the end of the tick:
    the minimal route needs no random draws because it has a single
    destination. Bags already on the belt move before new bags are admitted.
    """

    def __init__(self, config: SimulationConfig | None = None, *, seed: int = 42) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        self.config = config if config is not None else SimulationConfig()
        self.seed = seed
        self.rng = Random(seed)
        self.conveyor = Conveyor(self.config.conveyor)
        self._tick = 0
        self.waiting: deque[Baggage] = deque()
        self.generated_count = 0
        self.admitted_count = 0
        self.correctly_delivered_count = 0
        self.misdelivered_count = 0
        self._total_travel_time_s = 0.0
        # Only the exits of the last tick: no unbounded history.
        self.exited_this_tick: tuple[Baggage, ...] = ()
        self.events = EventLog()
        self._entrance_queued = False

    @property
    def tick(self) -> int:
        """Number of completed steps, initially zero."""
        return self._tick

    @property
    def time_s(self) -> float:
        """Simulated time in seconds, computed without accumulating rounding errors."""
        return self._tick * STEP_MS / 1000

    @property
    def exited_count(self) -> int:
        """All exits, correct and wrong, without a duplicate counter."""
        return self.correctly_delivered_count + self.misdelivered_count

    @property
    def in_transit_count(self) -> int:
        """Bags still on the belt, including stopped ones; waiting bags excluded."""
        return len(self.conveyor.baggage)

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
            waiting=len(self.waiting),
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
        outgoing = self._evaluate_transfers()
        self._apply_transfers(outgoing)
        self._generate()
        self._admit()
        self._update_entrance_queue()

    def _move(self) -> None:
        """Advances from the exit towards the entrance, using the updated position ahead.

        The front edge stops at the end of the belt or at the minimum gap from
        the rear edge of the bag ahead. Ready bags are removed only after every
        bag has finished moving.
        """
        distance = self.conveyor.config.speed_m_s * STEP_SECONDS
        front_limit = self.conveyor.config.length_m
        for baggage in reversed(self.conveyor.baggage):
            max_position = front_limit - baggage.length_m
            # max prevents tiny backward moves caused by rounding of the gap.
            baggage.position_m = max(
                baggage.position_m,
                min(baggage.position_m + distance, max_position),
            )
            front_limit = baggage.position_m - self.config.min_gap_m

    def _evaluate_transfers(self) -> tuple[Baggage, ...]:
        """Selects the exit without mutating the state observed after movement.

        On the minimal route only the most downstream bag can exit. The limit
        uses the same subtraction as movement, avoiding inconsistent comparisons
        due to rounding. No epsilon brings the exit forward.
        """
        if not self.conveyor.baggage:
            return ()
        baggage = self.conveyor.baggage[-1]
        if baggage.position_m >= self.conveyor.config.length_m - baggage.length_m:
            return (baggage,)
        return ()

    def _apply_transfers(self, outgoing: tuple[Baggage, ...]) -> None:
        """Applies the result of the tick's evaluation exactly once.

        The output unloads automatically. Movement is not repeated after the
        transfer: following bags use the freed space from the next tick.
        A newly admitted bag at the end of the belt also waits for the next tick.
        """
        self.exited_this_tick = outgoing
        for baggage in outgoing:
            if baggage.entered_at_s is None:
                raise ValueError("An exiting bag must have been admitted")
            self.conveyor.baggage.pop()
            baggage.conveyor_id = None
            baggage.exited_at_s = self.time_s
            if baggage.destination_id == self.config.output_id:
                self.correctly_delivered_count += 1
            else:
                self.misdelivered_count += 1
            self._total_travel_time_s += self.time_s - baggage.entered_at_s

    def _generate(self) -> None:
        """Queues every due arrival, without losing demand when the belt is full.

        The total is derived from elapsed time, without rounding an interval
        to ticks or accumulating fractions at every step. The first arrival
        happens after a full interval. The timestamp is that of the tick in
        which the arrival is detected (a delay shorter than one step).
        """
        due_count = int(self.tick * STEP_MS * self.config.arrival_rate_bags_s / 1000)
        while self.generated_count < due_count:
            self.generated_count += 1
            self.waiting.append(Baggage(
                id=f"bag-{self.generated_count}",
                destination_id=self.config.output_id,
                length_m=self.config.baggage_length_m,
                generated_at_s=self.time_s,
            ))

    def _admit(self) -> None:
        """Admits the first waiting bag if the entrance is free.

        The belt list is ordered from entrance to exit: the first element is
        the closest to the new bag. One admission per tick is enough because
        the new bag immediately occupies position zero.
        """
        if not self.waiting:
            return
        baggage = self.waiting[0]
        if baggage.length_m > self.conveyor.config.length_m:
            return
        if self.conveyor.baggage:
            nearest = self.conveyor.baggage[0]
            if nearest.position_m < baggage.length_m + self.config.min_gap_m:
                return
        self.waiting.popleft()
        baggage.conveyor_id = self.conveyor.config.id
        baggage.entered_at_s = self.time_s
        baggage.position_m = 0.0
        self.conveyor.baggage.insert(0, baggage)
        self.admitted_count += 1

    def _update_entrance_queue(self) -> None:
        """Records the start and end of the entrance queue, not every waiting tick.

        The queue exists when at least one bag is still waiting after
        admission. It is an informational event: the prolonged-wait warning
        will have its own thresholds.
        """
        queued = bool(self.waiting)
        if queued == self._entrance_queued:
            return
        self._entrance_queued = queued
        if queued:
            kind, message = "entrance_queue_started", "Entrance queue: no space on the belt"
        else:
            kind, message = "entrance_queue_cleared", "Entrance queue cleared"
        self.events.record(self.tick, self.time_s, Severity.INFO, kind, message,
                           element_id=self.config.input_id)
