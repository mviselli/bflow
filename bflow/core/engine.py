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
        # Belts entering each merge, in layout order: the order of the turns.
        self.merge_inputs = {node.id: [belt.id for belt in self.layout.belts
                                       if belt.target_id == node.id]
                             for node in self.layout.merges}
        # The belt each belt hands its bags to: the following belt, or the
        # belt leaving the merge it ends at. Belts ending at an output or a
        # sorter are not here (see _next_conveyor).
        self._next_conveyors = {}
        for belt in self.layout.belts:
            if belt.target_id in self.conveyors:
                self._next_conveyors[belt.id] = self.conveyors[belt.target_id]
            elif belt.source_id in self.merge_inputs:
                for belt_id in self.merge_inputs[belt.source_id]:
                    self._next_conveyors[belt_id] = self.conveyors[belt.id]
        # Belt whose bag each merge let through last; None before the first.
        self.last_merged: dict[str, str | None] = {node.id: None for node in self.layout.merges}
        # For each sorter, the branch leading to each output after it: the
        # layout allows one route per output, so the choice is predetermined.
        self.sorter_routes = {node.id: {output_id: belt.id
                                        for belt in self.layout.belts
                                        if belt.source_id == node.id
                                        for output_id in self._outputs_after(belt.id)}
                              for node in self.layout.sorters}
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
        leaving = self._resolve_merges(self._evaluate_transfers())
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

    def _outputs_after(self, element_id: str) -> set[str]:
        """The outputs a bag can reach from a belt or node, following the targets.

        The layout has no cycles, so the recursion always ends at outputs.
        """
        if element_id in self._output_ids:
            return {element_id}
        if element_id in self.conveyors:
            return self._outputs_after(self.conveyors[element_id].config.target_id)
        # A merge or sorter: the outputs after every belt leaving it.
        return set().union(*(self._outputs_after(belt.id) for belt in self.layout.belts
                             if belt.source_id == element_id))

    def _next_conveyor(self, conveyor: Conveyor, baggage: Baggage) -> Conveyor | None:
        """The belt that receives the front bag of a belt; None when it ends at an output.

        After a sorter it is the branch of the bag's destination.
        """
        target_id = conveyor.config.target_id
        if target_id in self.sorter_routes:
            return self.conveyors[self.sorter_routes[target_id][baggage.destination_id]]
        return self._next_conveyors.get(conveyor.config.id)

    def _has_entry_space(self, conveyor: Conveyor, baggage: Baggage) -> bool:
        """True if the bag fits at position zero, keeping the gap to the nearest bag."""
        if not conveyor.baggage:
            return True
        return conveyor.baggage[0].position_m >= baggage.length_m + self.layout.min_gap_m

    def _evaluate_transfers(self) -> tuple[Conveyor, ...]:
        """Returns the belts whose front bag is ready to leave, without mutating state.

        A bag is ready when its front edge is at the end of the belt. The
        limit uses the same subtraction as movement, avoiding inconsistent
        comparisons due to rounding; no epsilon brings the exit forward.
        An output always accepts the bag. The next belt (the following one,
        the one leaving a merge, or the branch of the bag's destination after
        a sorter) accepts it only if its entrance has space; otherwise the bag
        waits at the end of its belt, and the bags behind it wait too. Several
        belts can be ready for the same merge: _resolve_merges chooses one.
        """
        leaving = []
        for conveyor in self.conveyors.values():
            if not conveyor.baggage:
                continue
            baggage = conveyor.baggage[-1]
            if baggage.position_m < conveyor.config.length_m - baggage.length_m:
                continue
            next_conveyor = self._next_conveyor(conveyor, baggage)
            if next_conveyor is None or self._has_entry_space(next_conveyor, baggage):
                leaving.append(conveyor)
        return tuple(leaving)

    def _resolve_merges(self, ready: tuple[Conveyor, ...]) -> tuple[Conveyor, ...]:
        """Lets at most one bag per tick through each merge, taking turns; no mutation.

        Only one bag fits at the entrance of the belt leaving the merge, so
        the others wait. The turn goes to the first ready belt after the one
        let through last, in layout order and wrapping around: with bags
        waiting on every belt they pass one each in turn, and a belt that is
        the only one ready never waits for the others. Before the first bag
        the turn starts from the first belt. Belts not ending at a merge are
        kept as they are, in the same order.
        """
        ready_ids = {conveyor.config.id for conveyor in ready}
        chosen = set()
        for merge_id, belt_ids in self.merge_inputs.items():
            last = self.last_merged[merge_id]
            first = belt_ids.index(last) + 1 if last is not None else 0
            for offset in range(len(belt_ids)):
                belt_id = belt_ids[(first + offset) % len(belt_ids)]
                if belt_id in ready_ids:
                    chosen.add(belt_id)
                    break
        return tuple(conveyor for conveyor in ready
                     if conveyor.config.target_id not in self.merge_inputs
                     or conveyor.config.id in chosen)

    def _apply_transfers(self, leaving: tuple[Conveyor, ...]) -> None:
        """Moves the front bag of each selected belt, exactly once.

        On the next belt the bag starts at position zero, like a newly
        admitted bag; an output unloads it automatically. A merge remembers
        which belt it let through, for the next turn. Movement is not
        repeated after the transfer: following bags use the freed space, and
        the transferred bag moves, from the next tick.
        """
        exited = []
        for conveyor in leaving:
            baggage = conveyor.baggage.pop()
            target_id = conveyor.config.target_id
            if target_id in self.merge_inputs:
                self.last_merged[target_id] = conveyor.config.id
            next_conveyor = self._next_conveyor(conveyor, baggage)
            if next_conveyor is not None:
                baggage.conveyor_id = next_conveyor.config.id
                baggage.position_m = 0.0
                next_conveyor.baggage.insert(0, baggage)
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
