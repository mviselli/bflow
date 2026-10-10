"""The whole plant checked at every tick, in normal flow and under stress.

After each step a checker compares the engine with its state one tick
earlier: baggage conservation, spacing, routing, the entrance queues,
waiting at the end of a belt, the alternation at the merge, sorting
errors (decided once, counted once, and the only cause of a wrong exit),
the congestion warnings (start after 10 s above 80 %, clear below 60 %) and
the prolonged waits (a bag not advancing for 30 s warns until it advances)
the alarms (one open alarm for each fault, congestion and prolonged wait,
resolved when it ends, whether acknowledged or not) and the events
themselves (consecutive ids, recorded at the tick of the change, a
condition's start and end alternating, never repeated).
"""

from collections import Counter
from dataclasses import replace

import pytest

from bflow.core.engine import STEP_MS, STEP_SECONDS, Engine
from bflow.core.events import AlarmState, Severity
from bflow.core.layout import default_layout
from tests.layouts import compact_layout

# Rounding margin for positions, as in the other spacing tests.
EPSILON = 1e-9

# Events that start or end a condition: kind → (condition, starts it?). The
# subject of a condition is its bag, or else its element.
CONDITION_EVENTS = {
    "entrance_queue_started": ("entrance queue", True),
    "entrance_queue_cleared": ("entrance queue", False),
    "belt_stopped": ("stop", True),
    "belt_restarted": ("stop", False),
    "belt_fault": ("fault", True),
    "belt_repaired": ("fault", False),
    "congestion_started": ("congestion", True),
    "congestion_cleared": ("congestion", False),
    "prolonged_wait_started": ("prolonged wait", True),
    "prolonged_wait_resolved": ("prolonged wait", False),
}
# Events that happen at most once for each bag.
ONCE_PER_BAG = {"wrong_sorting", "wrong_exit"}
# Events of operator commands, applied between steps: they carry the tick
# before the step that follows.
COMMAND_EVENTS = {"belt_stopped", "belt_restarted", "belt_fault", "belt_repaired",
                  "input_rate_changed", "missort_probability_changed", "missort_forced",
                  "alarm_acknowledged"}


def number(bag):
    return int(bag.id.removeprefix("bag-"))


def at_end(conveyor, bag):
    return bag.position_m >= conveyor.config.length_m - bag.length_m


def halted_belts(engine):
    """Belts that may not move or hand over bags: stopped or faulty."""
    return {belt_id for belt_id, conveyor in engine.conveyors.items() if conveyor.halted}


class PlantChecker:
    """Remembers where every bag was, and checks the tick that follows."""

    def __init__(self, engine):
        self.engine = engine
        self.reachable = {belt_id: engine._outputs_after(belt_id) for belt_id in engine.conveyors}
        self.merge_output = {merge_id: next(conveyor for conveyor in engine.conveyors.values()
                                            if conveyor.config.source_id == merge_id)
                             for merge_id in engine.merge_inputs}
        self.last_admitted = {input_id: 0 for input_id in engine.waiting}
        self.admitted_count = {input_id: 0 for input_id in engine.waiting}
        # Wrong output of every bag missorted so far, and the wrong exits seen.
        self.missorted = {}
        self.wrong_exits = 0
        self.last_event_id = engine.events.last_id
        # Consecutive ticks each belt has been above 80 %, and its warning.
        self.ticks_above = {belt_id: 0 for belt_id in engine.conveyors}
        self.congested = {belt_id: False for belt_id in engine.conveyors}
        # Tick each bag on a belt last advanced, and the bags in a prolonged wait.
        self.advanced_at = {}
        self.long_waits = set()
        # Open alarms, those acknowledged among them, and the last id raised.
        self.open_alarms = set(engine.alarms)
        self.acknowledged = set()
        self.last_alarm_id = engine.last_alarm_id
        # Conditions on now, as (condition, subject), and the once-per-bag events seen.
        self.conditions = set()
        self.once_seen = set()
        # Every event seen, by kind: the engine's history keeps only the latest.
        # Also the tick of the first and last event of each kind.
        self.event_counts = Counter()
        self.first_tick = {}
        self.last_tick = {}
        self.remember()

    def remember(self):
        self.places = {bag.id: (bag.conveyor_id, bag.position_m)
                       for conveyor in self.engine.conveyors.values() for bag in conveyor.baggage}
        self.halted = halted_belts(self.engine)
        self.last_merged = dict(self.engine.last_merged)

    def check(self):
        engine = self.engine
        stats = engine.stats()
        assert stats.is_conserved
        for bag in engine.exited_this_tick:
            assert (bag.conveyor_id, bag.exited_at_s) == (None, engine.time_s)
            # Only a sorting error leads to a wrong exit.
            self.wrong_exits += bag.missorted_to_id is not None
        assert engine.misdelivered_count == self.wrong_exits

        on_belts = [bag for conveyor in engine.conveyors.values() for bag in conveyor.baggage]
        ids = [bag.id for bag in on_belts] + [bag.id for queue in engine.waiting.values()
                                              for bag in queue]
        assert len(ids) == len(set(ids)) == engine.generated_count - engine.exited_count

        entered = {}  # belt id → (bag, belt it came from or None) that arrived this tick
        for belt_id, conveyor in engine.conveyors.items():
            self.check_spacing(conveyor)
            for bag in conveyor.baggage:
                # Routing: the output it is sent to (its destination unless
                # missorted) is still ahead of it.
                assert bag.route_output_id in self.reachable[belt_id], bag
                before = self.places.get(bag.id)
                if before is None:
                    # Admitted this tick, at the start of its input belt.
                    assert conveyor in engine.input_conveyors.values()
                    assert (bag.position_m, bag.entered_at_s) == (0, engine.time_s)
                    entered.setdefault(belt_id, []).append((bag, None))
                elif before[0] == belt_id:
                    moved = bag.position_m - before[1]
                    limit = 0 if belt_id in self.halted else conveyor.config.speed_m_s * STEP_SECONDS
                    assert -EPSILON <= moved <= limit + EPSILON, bag
                else:
                    # One hop along the plant, to the belt chosen for this bag.
                    previous = engine.conveyors[before[0]]
                    assert previous.config.id not in self.halted
                    assert engine._next_conveyor(previous, bag) is conveyor
                    assert bag.position_m == 0
                    entered.setdefault(belt_id, []).append((bag, previous))
        assert all(len(bags) == 1 for bags in entered.values())

        self.check_queues(entered)
        self.check_waiting_at_belt_ends(entered)
        self.check_merges(entered)
        events = [event for event in engine.events.recent if event.id > self.last_event_id]
        self.check_events(events)
        self.check_sorting_errors(on_belts, events)
        self.check_congestion(events)
        self.check_prolonged_waits(on_belts, events)
        self.check_alarms(on_belts, events)
        self.event_counts.update(event.kind for event in events)
        for event in events:
            self.first_tick.setdefault(event.kind, event.tick)
            self.last_tick[event.kind] = event.tick
        self.last_event_id = engine.events.last_id
        self.remember()

    def check_events(self, events):
        """Events since the last tick: the next ids, at this tick, changes only.

        None was dropped from the history before being seen. Only a command
        event may carry the previous tick (commands are applied between
        steps). A condition starts only when it is off and ends only when it
        is on, so it is never recorded again while it lasts; an error and a
        wrong exit happen once per bag.
        """
        engine = self.engine
        assert [event.id for event in events] == list(
            range(self.last_event_id + 1, engine.events.last_id + 1))
        for event in events:
            assert event.time_s == event.tick * STEP_MS / 1000
            assert event.tick == engine.tick or (
                event.tick == engine.tick - 1 and event.kind in COMMAND_EVENTS), event
            if event.kind in CONDITION_EVENTS:
                condition, starts = CONDITION_EVENTS[event.kind]
                key = (condition, event.baggage_id or event.element_id)
                assert (key in self.conditions) != starts, event
                if starts:
                    self.conditions.add(key)
                else:
                    self.conditions.remove(key)
            elif event.kind in ONCE_PER_BAG:
                assert (event.kind, event.baggage_id) not in self.once_seen, event
                self.once_seen.add((event.kind, event.baggage_id))

    def check_sorting_errors(self, on_belts, events):
        """A missort is decided once, never changes, and records exactly one error event."""
        new = {}
        for bag in on_belts:
            if bag.missorted_to_id is None:
                assert bag.id not in self.missorted
            elif bag.id in self.missorted:
                assert bag.missorted_to_id == self.missorted[bag.id]
            else:
                assert bag.missorted_to_id != bag.destination_id
                new[bag.id] = bag.missorted_to_id
        errors = {event.baggage_id for event in events if event.kind == "wrong_sorting"}
        assert errors == set(new)
        assert len([event for event in events if event.kind == "wrong_sorting"]) == len(new)
        self.missorted.update(new)

    def check_congestion(self, events):
        """Congested after 201 ticks in a row above 80 % (10 s), until below 60 %.

        Each start is one warning event and each clearing one info event.
        """
        engine = self.engine
        started = {event.element_id for event in events if event.kind == "congestion_started"}
        cleared = {event.element_id for event in events if event.kind == "congestion_cleared"}
        for belt_id, conveyor in engine.conveyors.items():
            occupancy = len(conveyor.baggage) / engine.belt_capacities[belt_id]
            self.ticks_above[belt_id] = self.ticks_above[belt_id] + 1 if occupancy > 0.8 else 0
            was = self.congested[belt_id]
            expected = occupancy >= 0.6 if was else self.ticks_above[belt_id] > 200
            assert conveyor.congested == expected, (belt_id, occupancy)
            assert (belt_id in started) == (expected and not was)
            assert (belt_id in cleared) == (was and not expected)
            self.congested[belt_id] = expected

    def check_prolonged_waits(self, on_belts, events):
        """A bag warns after 600 ticks (30 s) without advancing, until it advances or exits.

        Advancing is entering the plant, moving forward by more than rounding,
        or passing to another belt or an output. Each start and each
        resolution is one event, and the bag is never removed.
        """
        engine = self.engine
        started, resolved = set(), set()
        for bag in engine.exited_this_tick:
            self.advanced_at.pop(bag.id)
            if bag.id in self.long_waits:
                resolved.add(bag.id)
            assert not bag.prolonged_wait
        for bag in on_belts:
            before = self.places.get(bag.id)
            if (before is None or before[0] != bag.conveyor_id
                    or bag.position_m > before[1] + EPSILON):
                self.advanced_at[bag.id] = engine.tick
            expected = engine.tick - self.advanced_at[bag.id] >= 600
            assert bag.prolonged_wait == expected, bag
            if expected and bag.id not in self.long_waits:
                started.add(bag.id)
            if not expected and bag.id in self.long_waits:
                resolved.add(bag.id)
        self.long_waits = (self.long_waits | started) - resolved
        kinds = Counter(event.kind for event in events)
        assert {event.baggage_id for event in events
                if event.kind == "prolonged_wait_started"} == started
        assert {event.baggage_id for event in events
                if event.kind == "prolonged_wait_resolved"} == resolved
        assert (kinds["prolonged_wait_started"], kinds["prolonged_wait_resolved"]) == (
            len(started), len(resolved))

    def check_alarms(self, on_belts, events):
        """Each lasting condition has exactly one open alarm, until it ends.

        Alarms are raised with the next ids, one start event each; an
        acknowledgement (one event) never returns to active and does not end
        the condition; the end resolves the alarm with one event.
        """
        engine = self.engine
        conditions = sorted(
            [("belt_fault", belt_id) for belt_id, conveyor in engine.conveyors.items()
             if conveyor.faulty]
            + [("congestion", belt_id) for belt_id, conveyor in engine.conveyors.items()
               if conveyor.congested]
            + [("prolonged_wait", bag.id) for bag in on_belts if bag.prolonged_wait])
        assert sorted((alarm.kind, alarm.baggage_id or alarm.element_id)
                      for alarm in engine.alarms.values()) == conditions
        # The statistics: occurrences by kind add up, and active alarms are
        # the conditions open now.
        stats = engine.stats()
        assert stats.errors == stats.faults + stats.wrong_sortings
        assert stats.warnings == stats.congestions + stats.prolonged_waits
        assert stats.active_errors == sum(kind == "belt_fault" for kind, _ in conditions)
        assert stats.active_warnings == len(conditions) - stats.active_errors
        raised = set(range(self.last_alarm_id + 1, engine.last_alarm_id + 1))
        assert set(engine.alarms) - self.open_alarms == raised - {
            alarm.id for alarm in engine.resolved_alarms}
        resolved = (self.open_alarms | raised) - set(engine.alarms)
        acknowledged = {alarm.id for alarm in engine.alarms.values()
                        if alarm.state is AlarmState.ACKNOWLEDGED}
        assert self.acknowledged & set(engine.alarms) <= acknowledged
        assert all(alarm.state is AlarmState.RESOLVED for alarm in engine.resolved_alarms)
        starts = [event.alarm_id for event in events if event.kind in {
            "belt_fault", "congestion_started", "prolonged_wait_started"}]
        ends = [event.alarm_id for event in events if event.kind in {
            "belt_repaired", "congestion_cleared", "prolonged_wait_resolved"}]
        acks = [event.alarm_id for event in events if event.kind == "alarm_acknowledged"]
        assert sorted(starts) == sorted(raised)
        assert sorted(ends) == sorted(resolved)
        assert len(acks) == len(set(acks)) and not set(acks) & self.acknowledged
        self.acknowledged = (self.acknowledged | set(acks)) & set(engine.alarms)
        assert self.acknowledged == acknowledged
        self.open_alarms = set(engine.alarms)
        self.last_alarm_id = engine.last_alarm_id

    def check_spacing(self, conveyor):
        gap = self.engine.layout.min_gap_m
        bags = conveyor.baggage
        for bag in bags:
            assert bag.conveyor_id == conveyor.config.id
            assert 0 <= bag.position_m <= conveyor.config.length_m - bag.length_m + EPSILON
        for rear, front in zip(bags, bags[1:]):
            assert rear.position_m + rear.length_m + gap <= front.position_m + EPSILON

    def check_queues(self, entered):
        """Each input admits its oldest bag, and nobody waits while its belt has space.

        The input's waiting bags are its last generated ones (the page numbers
        the passengers in its queue from generated − waiting).
        """
        engine = self.engine
        for input_id, queue in engine.waiting.items():
            conveyor = engine.input_conveyors[input_id]
            for bag, previous in entered.get(conveyor.config.id, []):
                if previous is None:
                    assert number(bag) > self.last_admitted[input_id]
                    self.last_admitted[input_id] = number(bag)
                    self.admitted_count[input_id] += 1
            assert engine.generated_by_input[input_id] - len(queue) == self.admitted_count[input_id]
            if queue:
                assert number(queue[0]) > self.last_admitted[input_id]
                assert not engine._has_entry_space(conveyor, queue[0])

    def check_waiting_at_belt_ends(self, entered):
        """A bag at the end of a running belt waits only for space, or for its merge turn."""
        engine = self.engine
        for belt_id, conveyor in engine.conveyors.items():
            if conveyor.halted or not conveyor.baggage or not at_end(conveyor, conveyor.baggage[-1]):
                continue
            bag = conveyor.baggage[-1]
            if self.places.get(bag.id, (None,))[0] != belt_id:
                continue  # arrived this tick: it can leave from the next one
            next_conveyor = engine._next_conveyor(conveyor, bag)
            assert next_conveyor is not None, f"{bag.id} should have left through its output"
            if engine._has_entry_space(next_conveyor, bag):
                # Only a merge can hold it back: another belt won this tick.
                assert conveyor.config.target_id in engine.merge_inputs, bag
                assert entered.get(next_conveyor.config.id), bag

    def check_merges(self, entered):
        """The merge lets through the first ready belt after the last one, wrapping around."""
        engine = self.engine
        for merge_id, belt_ids in engine.merge_inputs.items():
            arrivals = entered.get(self.merge_output[merge_id].config.id, [])
            if not arrivals:
                assert engine.last_merged[merge_id] == self.last_merged[merge_id]
                continue
            ((_, previous),) = arrivals
            winner = previous.config.id
            assert engine.last_merged[merge_id] == winner
            last = self.last_merged[merge_id]
            first = belt_ids.index(last) + 1 if last is not None else 0
            skipped = []
            for offset in range(len(belt_ids)):
                belt_id = belt_ids[(first + offset) % len(belt_ids)]
                if belt_id == winner:
                    break
                skipped.append(belt_id)
            for belt_id in skipped:
                conveyor = engine.conveyors[belt_id]
                waiting = [bag for bag in conveyor.baggage[-1:]
                           if self.places.get(bag.id, (None,))[0] == belt_id]
                # A skipped belt had no bag ready at the merge.
                assert conveyor.halted or not waiting or not at_end(conveyor, waiting[0])


def with_rates(rate, layout=None):
    layout = layout or compact_layout()
    return replace(layout, inputs=tuple(replace(node, arrival_rate_bags_s=rate)
                                        for node in layout.inputs))


def with_slow_branch_2():
    layout = compact_layout()
    return replace(layout, belts=tuple(replace(belt, speed_m_s=0.1) if belt.id == "branch-2"
                                       else belt for belt in layout.belts))


# Layout, commands by tick (engine method and arguments), number of ticks. The compact plant has three-way
# junctions; the demo plant chains two-way merges and diverts.
SCENARIOS = {
    "normal flow": (compact_layout(), {}, 12000),
    "saturated inputs": (with_rates(1), {}, 6000),
    "feeder B stopped for 120 s": (compact_layout(), {
        2000: ("stop_belt", "feeder-b"), 4400: ("restart_belt", "feeder-b")}, 12000),
    "collector stopped for 60 s": (compact_layout(), {
        3000: ("stop_belt", "collector"), 4200: ("restart_belt", "collector")}, 12000),
    "slow branch 2": (with_slow_branch_2(), {}, 6000),
    "demo: normal flow": (default_layout(), {}, 12000),
    "demo: saturated desks": (with_rates(1, default_layout()), {}, 6000),
    "demo: island B stopped for 120 s": (default_layout(), {
        3000: ("stop_belt", "island-b-3"), 5400: ("restart_belt", "island-b-3")}, 12000),
    "demo: branch 2 stopped for 120 s": (default_layout(), {
        3000: ("stop_belt", "branch-2"), 5400: ("restart_belt", "branch-2")}, 12000),
    "collector faulty for 60 s, restart refused": (compact_layout(), {
        3000: ("fault_belt", "collector"), 3600: ("restart_belt", "collector"),
        4200: ("repair_belt", "collector")}, 12000),
    "demo: line 2 faulty for 120 s": (default_layout(), {
        3000: ("fault_belt", "line-2"), 5400: ("repair_belt", "line-2")}, 12000),
    "demo: line 2 faulty, its alarm and a congestion acknowledged": (default_layout(), {
        3000: ("fault_belt", "line-2"), 3100: ("acknowledge_alarm", 1),
        4000: ("acknowledge_alarm", 2), 4001: ("acknowledge_alarm", 2),
        5400: ("repair_belt", "line-2")}, 12000),
    "wrong sorting 10 %": (compact_layout(), {0: ("set_missort_probability", 0.1)}, 12000),
    "demo: wrong sorting 20 % while branch 2 is stopped": (default_layout(), {
        0: ("set_missort_probability", 0.2), 3000: ("stop_belt", "branch-2"),
        4200: ("restart_belt", "branch-2")}, 12000),
    "demo: forced errors": (default_layout(), {
        1000: ("force_missort",), 1001: ("force_missort",), 3000: ("force_missort",)}, 6000),
}


def run(layout, commands, ticks, seed=42):
    return run_checked(layout, commands, ticks, seed).engine


def run_checked(layout, commands, ticks, seed=42):
    """Runs a scenario under the checker and returns the checker (and so the engine)."""
    engine = Engine(layout, seed=seed)
    checker = PlantChecker(engine)
    for tick in range(ticks):
        if tick in commands:
            method, *args = commands[tick]
            getattr(engine, method)(*args)
            checker.halted = halted_belts(engine)
        engine.step()
        checker.check()
    return checker


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_tick_of_the_plant_respects_the_rules(name):
    engine = run(*SCENARIOS[name])
    stats = engine.stats()
    assert stats.correctly_delivered > 0
    assert all(node.correctly_delivered > 0 for node in stats.outputs)


def test_below_capacity_every_output_gets_about_a_third_and_no_queue_is_left():
    engine = run(*SCENARIOS["normal flow"])
    stats = engine.stats()
    assert stats.waiting == 0
    for node in stats.outputs:
        assert 0.25 < node.correctly_delivered / stats.correctly_delivered < 0.42


def test_after_a_stop_the_queue_clears_while_demand_is_below_capacity():
    engine = run(*SCENARIOS["feeder B stopped for 120 s"])
    assert engine.waiting_count == 0


def test_saturated_inputs_leave_queues_at_every_input_and_full_feeders():
    engine = run(*SCENARIOS["saturated inputs"])
    stats = engine.stats()
    assert all(node.waiting > 0 for node in stats.inputs)
    feeders = [belt for belt in stats.belts if belt.belt_id.startswith("feeder")]
    assert all(belt.occupancy >= 0.8 for belt in feeders)


def test_the_demo_plant_below_capacity_serves_every_output_with_no_queue():
    engine = run(*SCENARIOS["demo: normal flow"])
    stats = engine.stats()
    assert stats.waiting == 0
    for node in stats.outputs:
        assert 0.2 < node.correctly_delivered / stats.correctly_delivered < 0.3


def test_chained_merges_give_the_desk_nearest_the_line_the_largest_share():
    # Saturated, each island gets half of the line; within an island the
    # last desk gets half of that, the two before it a quarter each.
    engine = run(*SCENARIOS["demo: saturated desks"])
    admitted = {input_id: engine.generated_by_input[input_id] - len(queue)
                for input_id, queue in engine.waiting.items()}
    total = sum(admitted.values())
    for island in "ab":
        assert 0.2 < admitted[f"input-{island}3"] / total < 0.27
        for desk in "12":
            assert 0.1 < admitted[f"input-{island}{desk}"] / total < 0.15


def test_a_stopped_island_queues_only_its_own_desks_and_then_clears():
    engine = Engine(default_layout())
    for tick in range(5400):
        if tick == 3000:
            engine.stop_belt("island-b-3")
        engine.step()
    stats = engine.stats()
    waiting = {node.input_id: node.waiting for node in stats.inputs}
    assert all(waiting[f"input-b{desk}"] > 0 for desk in "123")
    assert all(waiting[f"input-a{desk}"] == 0 for desk in "123")
    engine = run(*SCENARIOS["demo: island B stopped for 120 s"])
    assert engine.waiting_count == 0


def test_a_stopped_branch_blocks_the_whole_line_behind_its_divert():
    engine = Engine(default_layout())
    for tick in range(5400):
        if tick == 3000:
            engine.stop_belt("branch-2")
        engine.step()
    # A bag for output 2 waits at divert 2 and holds up every bag behind it.
    head = engine.conveyors["line-2"].baggage[-1]
    assert head.destination_id == "output-2"
    assert all(node.waiting > 0 for node in engine.stats().inputs)
    engine = run(*SCENARIOS["demo: branch 2 stopped for 120 s"])
    assert engine.waiting_count == 0


def test_after_a_fault_is_repaired_the_queue_clears_while_demand_is_below_capacity():
    engine = Engine(default_layout())
    for tick in range(5400):
        if tick == 3000:
            engine.fault_belt("line-2")
        engine.step()
    # The whole sort line backs up to every desk while line 2 is faulty.
    assert all(node.waiting > 0 for node in engine.stats().inputs)
    engine = run(*SCENARIOS["demo: line 2 faulty for 120 s"])
    assert engine.waiting_count == 0
    assert engine.stats().errors == 1


def test_a_fault_queues_warns_and_after_the_repair_the_plant_recovers_in_that_order():
    # The phase's story on the demo plant, demand below capacity, every tick
    # under the checker: line 2 faulty from tick 3000, repaired at 5400.
    checker = run_checked(*SCENARIOS["demo: line 2 faulty for 120 s"])
    engine, first, last = checker.engine, checker.first_tick, checker.last_tick
    fault, repair = first["belt_fault"], first["belt_repaired"]
    assert (fault, repair) == (3000, 5400)
    # Nothing to warn about before the fault.
    assert min(first[kind] for kind in ("congestion_started", "prolonged_wait_started",
                                        "entrance_queue_started")) > fault
    # Faulty: the line fills, the bags held on it warn exactly 30 s after
    # it stopped, and the queue reaches the desks before the repair.
    assert first["prolonged_wait_started"] == fault + 600
    assert fault < first["congestion_started"] < first["entrance_queue_started"] < repair
    # Repaired: every waiting bag moves again, and the desks' queues clear.
    assert repair < first["prolonged_wait_resolved"]
    assert checker.event_counts["prolonged_wait_resolved"] == checker.event_counts["prolonged_wait_started"]
    assert checker.event_counts["entrance_queue_cleared"] == checker.event_counts["entrance_queue_started"]
    assert engine.waiting_count == 0
    # Then the congestions clear as the backlog drains, and no alarm is left.
    while engine.alarms:
        assert engine.tick < 20000
        engine.step()
        checker.check()
    stats = engine.stats()
    assert (stats.errors, stats.faults, stats.active_errors, stats.active_warnings) == (1, 1, 0, 0)
    assert stats.warnings == checker.event_counts["congestion_started"] + checker.event_counts[
        "prolonged_wait_started"]
    assert stats.is_conserved


def test_acknowledged_alarms_stay_open_until_the_repair_and_the_queue_clears():
    checker = run_checked(*SCENARIOS["demo: line 2 faulty, its alarm and a congestion acknowledged"])
    engine = checker.engine
    # Alarm 1 (the fault) and alarm 2 acknowledged; the repeat of alarm 2 adds nothing.
    assert checker.event_counts["alarm_acknowledged"] == 2
    assert engine.waiting_count == 0
    assert engine.stats().errors == 1
    # Once the backlog has gone, every alarm is resolved.
    for _ in range(6000):
        engine.step()
    assert engine.alarms == {}


def test_an_acknowledged_fault_still_halts_the_line_until_the_repair():
    engine = Engine(default_layout())
    for tick in range(5400):
        if tick == 3000:
            engine.fault_belt("line-2")
        if tick == 3100:
            engine.acknowledge_alarm(1)
        engine.step()
    fault = engine.alarms[1]
    assert (fault.kind, fault.state) == ("belt_fault", AlarmState.ACKNOWLEDGED)
    assert engine.conveyors["line-2"].faulty
    assert all(node.waiting > 0 for node in engine.stats().inputs)
    # The scenario above acknowledges alarm 2 at tick 4000: it exists by then.
    assert engine.last_alarm_id > 2


def test_two_forced_errors_give_two_errors_and_two_wrong_exits():
    # The request repeated at tick 1001, before a bag reached a sorter, adds nothing.
    engine = run(*SCENARIOS["demo: forced errors"])
    stats = engine.stats()
    assert (stats.errors, stats.misdelivered) == (2, 2)


def test_a_stopped_branch_congests_the_line_behind_it_and_the_warnings_clear_after_restart():
    checker = run_checked(*SCENARIOS["demo: branch 2 stopped for 120 s"])
    engine = checker.engine
    # The line backs up to every desk: each belt on the way warns once (line-2
    # again while the backlog drains after the restart), and so do the bags
    # held still for 30 s.
    congested = set(engine.conveyors) - {"line-3", "line-4", "branch-1", "branch-2", "branch-3"}
    assert checker.event_counts["congestion_started"] == len(congested) + 1
    assert checker.event_counts["prolonged_wait_started"] > 0
    assert engine.stats().warnings == (checker.event_counts["congestion_started"]
                                       + checker.event_counts["prolonged_wait_started"])
    assert checker.event_counts["prolonged_wait_resolved"] == checker.event_counts[
        "prolonged_wait_started"]
    # Once the backlog has gone, every warning has cleared.
    for _ in range(6000):
        engine.step()
    assert not any(conveyor.congested for conveyor in engine.conveyors.values())


def test_the_demo_plant_below_capacity_raises_no_congestion():
    engine = run(*SCENARIOS["demo: normal flow"])
    assert engine.stats().warnings == 0


def unfair_merge(engine):
    """The merge always lets the last ready belt through: no turns."""
    def resolve(ready):
        others = tuple(conveyor for conveyor in ready if conveyor.config.target_id != "merge")
        return others + tuple(conveyor for conveyor in ready
                              if conveyor.config.target_id == "merge")[-1:]
    engine._resolve_merges = resolve


def lazy_feeder(engine):
    """Feeder B never hands over its bags, even with space ahead."""
    evaluate = engine._evaluate_transfers
    engine._evaluate_transfers = lambda: tuple(conveyor for conveyor in evaluate()
                                               if conveyor.config.id != "feeder-b")


def lazy_admission(engine):
    """Inputs admit only on odd ticks, leaving bags waiting next to free space."""
    admit = engine._admit
    engine._admit = lambda: admit() if engine.tick % 2 else None


def wrong_branch(engine):
    """The sorter swaps the branches of outputs 1 and 2."""
    routes = engine.sorter_routes["sorter"]
    routes["output-1"], routes["output-2"] = routes["output-2"], routes["output-1"]


def error_counted_twice(engine):
    """Every sorting error records a second error event."""
    engine.set_missort_probability(0.2)
    missort = engine._missort

    def twice(baggage, sorter_id):
        missort(baggage, sorter_id)
        engine.events.record(engine.tick, engine.time_s, Severity.ERROR, "wrong_sorting",
                             "Counted again", element_id=sorter_id, baggage_id=baggage.id)
    engine._missort = twice


def sorter_changes_its_mind(engine):
    """The sorter decides again at every tick for a bag waiting at it."""
    engine.set_missort_probability(0.5)
    sort = engine._sort

    def again():
        for conveyor in engine.conveyors.values():
            for bag in conveyor.baggage:
                bag.sorted_at_id = bag.missorted_to_id = None
        sort()
    engine._sort = again


def impatient_congestion(engine):
    """Congestion starts after 5 s above 80 % instead of 10 s."""
    update = engine._update_congestion

    def sooner():
        for belt_id, since in engine._above_since.items():
            if since is not None and since == engine.tick - 1:
                engine._above_since[belt_id] = since - 100
        update()
    engine._update_congestion = sooner


@pytest.mark.parametrize("sabotage", [unfair_merge, lazy_feeder, lazy_admission, wrong_branch,
                                      error_counted_twice, sorter_changes_its_mind,
                                      impatient_congestion])
def test_the_checker_notices_a_broken_rule(sabotage):
    engine = Engine(with_rates(1))
    checker = PlantChecker(engine)
    sabotage(engine)
    with pytest.raises(AssertionError):
        for _ in range(3000):
            engine.step()
            checker.check()


def test_the_checker_notices_a_faulty_belt_that_keeps_moving():
    engine = Engine(with_rates(1))
    checker = PlantChecker(engine)
    move = engine._move

    def move_ignoring_faults():
        faulty = [conveyor for conveyor in engine.conveyors.values() if conveyor.faulty]
        for conveyor in faulty:
            conveyor.faulty = False
        move()
        for conveyor in faulty:
            conveyor.faulty = True

    engine._move = move_ignoring_faults
    with pytest.raises(AssertionError):
        for tick in range(3000):
            if tick == 500:
                engine.fault_belt("collector")
                checker.halted = halted_belts(engine)
            engine.step()
            checker.check()


def waits_never_resolve(engine):
    """A bag that advances again keeps its prolonged-wait warning."""
    def advanced(baggage):
        baggage.moved_at_s = engine.time_s
    engine._advanced = advanced


def impatient_waits(engine):
    """Bags warn after 15 s without advancing instead of 30 s."""
    update = engine._update_prolonged_waits

    def sooner():
        for conveyor in engine.conveyors.values():
            for bag in conveyor.baggage:
                if bag.moved_at_s == engine.time_s - 0.05:
                    bag.moved_at_s -= 15
        update()
    engine._update_prolonged_waits = sooner


@pytest.mark.parametrize("sabotage", [waits_never_resolve, impatient_waits])
def test_the_checker_notices_a_broken_prolonged_wait(sabotage):
    engine = Engine(with_rates(1))
    checker = PlantChecker(engine)
    sabotage(engine)
    with pytest.raises(AssertionError):
        for tick in range(3000):
            if tick == 100:
                engine.stop_belt("collector")
                checker.halted = halted_belts(engine)
            if tick == 1300:
                engine.restart_belt("collector")
                checker.halted = halted_belts(engine)
            engine.step()
            checker.check()


def acknowledgement_repairs(engine):
    """Acknowledging an alarm also clears the fault."""
    acknowledge = engine.acknowledge_alarm

    def and_repair(alarm_id):
        acknowledge(alarm_id)
        for conveyor in engine.conveyors.values():
            conveyor.faulty = False
    engine.acknowledge_alarm = and_repair


def alarms_never_resolve(engine):
    """The end of a condition records its event but leaves the alarm open."""
    def resolve(kind, event_kind, message, *, element_id, baggage_id=None):
        engine.events.record(engine.tick, engine.time_s, Severity.INFO, event_kind, message,
                             element_id=element_id, baggage_id=baggage_id)
    engine._resolve_alarm = resolve


def acknowledgement_reopens(engine):
    """An acknowledged alarm goes back to active at the next tick."""
    step = engine.step

    def forget():
        for alarm in engine.alarms.values():
            alarm.acknowledged_at_s = None
        step()
    engine.step = forget


@pytest.mark.parametrize("sabotage", [acknowledgement_repairs, alarms_never_resolve,
                                      acknowledgement_reopens])
def test_the_checker_notices_broken_alarms(sabotage):
    engine = Engine(with_rates(1))
    checker = PlantChecker(engine)
    sabotage(engine)
    with pytest.raises(AssertionError):
        for tick in range(3000):
            if tick == 100:
                engine.fault_belt("collector")
            if tick == 200:
                engine.acknowledge_alarm(1)
            if tick == 1300:
                engine.repair_belt("collector")
            checker.halted = halted_belts(engine)
            engine.step()
            checker.check()


def noisy_entrance_queues(engine):
    """A queue records its start again at every tick while it lasts."""
    def update():
        for input_id, queue in engine.waiting.items():
            if queue:
                engine.events.record(engine.tick, engine.time_s, Severity.INFO,
                                     "entrance_queue_started", "Entrance queue",
                                     element_id=input_id)
    engine._update_entrance_queues = update


def repeated_stop_events(engine):
    """Stopping a stopped belt records another stop."""
    set_stopped = engine._set_stopped

    def always(belt_id, stopped):
        if engine.conveyors[belt_id].stopped == stopped:
            engine.events.record(engine.tick, engine.time_s, Severity.INFO,
                                 "belt_stopped" if stopped else "belt_restarted", "Again",
                                 element_id=belt_id)
        set_stopped(belt_id, stopped)
    engine._set_stopped = always


def late_events(engine):
    """Congestion warnings recorded with the tick before the change."""
    update = engine._update_congestion

    def earlier():
        engine._tick -= 1
        update()
        engine._tick += 1
    engine._update_congestion = earlier


@pytest.mark.parametrize("sabotage", [noisy_entrance_queues, repeated_stop_events, late_events])
def test_the_checker_notices_repeated_or_misplaced_events(sabotage):
    engine = Engine(with_rates(1))
    checker = PlantChecker(engine)
    sabotage(engine)
    with pytest.raises(AssertionError):
        for tick in range(3000):
            if tick in (100, 101):
                engine.stop_belt("collector")
            if tick in (1300, 1301):
                engine.restart_belt("collector")
            checker.halted = halted_belts(engine)
            engine.step()
            checker.check()


def test_without_sabotage_the_same_stop_passes_the_checker():
    checker = run_checked(with_rates(1), {100: ("stop_belt", "collector"),
                                          1300: ("restart_belt", "collector")}, 3000)
    assert checker.event_counts["prolonged_wait_started"] > 0
    assert checker.event_counts["prolonged_wait_resolved"] > 0


def test_without_sabotage_the_same_fault_and_acknowledgement_pass_the_checker():
    checker = run_checked(with_rates(1), {100: ("fault_belt", "collector"),
                                          200: ("acknowledge_alarm", 1),
                                          1300: ("repair_belt", "collector")}, 3000)
    assert checker.event_counts["alarm_acknowledged"] == 1
    assert checker.event_counts["belt_repaired"] == 1
