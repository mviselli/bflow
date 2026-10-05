"""The whole plant checked at every tick, in normal flow and under stress.

After each step a checker compares the engine with its state one tick
earlier: baggage conservation, spacing, routing, the entrance queues,
waiting at the end of a belt, the alternation at the merge, sorting
errors (decided once, counted once, and the only cause of a wrong exit) and
the congestion warnings (start after 10 s above 80 %, clear below 60 %).
"""

from dataclasses import replace

import pytest

from bflow.core.engine import STEP_SECONDS, Engine
from bflow.core.events import Severity
from bflow.core.layout import default_layout
from tests.layouts import compact_layout

# Rounding margin for positions, as in the other spacing tests.
EPSILON = 1e-9


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
        # Wrong output of every bag missorted so far, and the wrong exits seen.
        self.missorted = {}
        self.wrong_exits = 0
        self.last_event_id = engine.events.last_id
        # Consecutive ticks each belt has been above 80 %, and its warning.
        self.ticks_above = {belt_id: 0 for belt_id in engine.conveyors}
        self.congested = {belt_id: False for belt_id in engine.conveyors}
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
        self.check_sorting_errors(on_belts, events)
        self.check_congestion(events)
        self.last_event_id = engine.events.last_id
        self.remember()

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

    def check_spacing(self, conveyor):
        gap = self.engine.layout.min_gap_m
        bags = conveyor.baggage
        for bag in bags:
            assert bag.conveyor_id == conveyor.config.id
            assert 0 <= bag.position_m <= conveyor.config.length_m - bag.length_m + EPSILON
        for rear, front in zip(bags, bags[1:]):
            assert rear.position_m + rear.length_m + gap <= front.position_m + EPSILON

    def check_queues(self, entered):
        """Each input admits its oldest bag, and nobody waits while its belt has space."""
        engine = self.engine
        for input_id, queue in engine.waiting.items():
            conveyor = engine.input_conveyors[input_id]
            for bag, previous in entered.get(conveyor.config.id, []):
                if previous is None:
                    assert number(bag) > self.last_admitted[input_id]
                    self.last_admitted[input_id] = number(bag)
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
    "wrong sorting 10 %": (compact_layout(), {0: ("set_missort_probability", 0.1)}, 12000),
    "demo: wrong sorting 20 % while branch 2 is stopped": (default_layout(), {
        0: ("set_missort_probability", 0.2), 3000: ("stop_belt", "branch-2"),
        4200: ("restart_belt", "branch-2")}, 12000),
    "demo: forced errors": (default_layout(), {
        1000: ("force_missort",), 1001: ("force_missort",), 3000: ("force_missort",)}, 6000),
}


def run(layout, commands, ticks, seed=42):
    engine = Engine(layout, seed=seed)
    checker = PlantChecker(engine)
    for tick in range(ticks):
        if tick in commands:
            method, *args = commands[tick]
            getattr(engine, method)(*args)
            checker.halted = halted_belts(engine)
        engine.step()
        checker.check()
    return engine


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


def test_two_forced_errors_give_two_errors_and_two_wrong_exits():
    # The request repeated at tick 1001, before a bag reached a sorter, adds nothing.
    engine = run(*SCENARIOS["demo: forced errors"])
    stats = engine.stats()
    assert (stats.errors, stats.misdelivered) == (2, 2)


def test_a_stopped_branch_congests_the_line_behind_it_and_the_warnings_clear_after_restart():
    engine = run(*SCENARIOS["demo: branch 2 stopped for 120 s"])
    started = [event.element_id for event in engine.events.recent
               if event.kind == "congestion_started"]
    # The line backs up to every desk: each belt on the way warns once (line-2
    # again while the backlog drains after the restart).
    assert set(started) == set(engine.conveyors) - {"line-3", "line-4", "branch-1", "branch-2",
                                                    "branch-3"}
    assert engine.stats().warnings == len(started) == len(set(started)) + 1
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
