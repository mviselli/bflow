"""The whole plant checked at every tick, in normal flow and under stress.

After each step a checker compares the engine with its state one tick
earlier: baggage conservation, spacing, routing, the entrance queues,
waiting at the end of a belt and the alternation at the merge.
"""

from dataclasses import replace

import pytest

from bflow.core.engine import STEP_SECONDS, Engine
from bflow.core.layout import default_layout

# Rounding margin for positions, as in the other spacing tests.
EPSILON = 1e-9


def number(bag):
    return int(bag.id.removeprefix("bag-"))


def at_end(conveyor, bag):
    return bag.position_m >= conveyor.config.length_m - bag.length_m


class PlantChecker:
    """Remembers where every bag was, and checks the tick that follows."""

    def __init__(self, engine):
        self.engine = engine
        self.reachable = {belt_id: engine._outputs_after(belt_id) for belt_id in engine.conveyors}
        self.merge_output = {merge_id: next(conveyor for conveyor in engine.conveyors.values()
                                            if conveyor.config.source_id == merge_id)
                             for merge_id in engine.merge_inputs}
        self.last_admitted = {input_id: 0 for input_id in engine.waiting}
        self.remember()

    def remember(self):
        self.places = {bag.id: (bag.conveyor_id, bag.position_m)
                       for conveyor in self.engine.conveyors.values() for bag in conveyor.baggage}
        self.stopped = {belt_id for belt_id, conveyor in self.engine.conveyors.items()
                        if conveyor.stopped}
        self.last_merged = dict(self.engine.last_merged)

    def check(self):
        engine = self.engine
        stats = engine.stats()
        assert stats.is_conserved
        assert engine.misdelivered_count == 0
        for bag in engine.exited_this_tick:
            assert (bag.conveyor_id, bag.exited_at_s) == (None, engine.time_s)

        on_belts = [bag for conveyor in engine.conveyors.values() for bag in conveyor.baggage]
        ids = [bag.id for bag in on_belts] + [bag.id for queue in engine.waiting.values()
                                              for bag in queue]
        assert len(ids) == len(set(ids)) == engine.generated_count - engine.exited_count

        entered = {}  # belt id → (bag, belt it came from or None) that arrived this tick
        for belt_id, conveyor in engine.conveyors.items():
            self.check_spacing(conveyor)
            for bag in conveyor.baggage:
                # Routing: the bag's destination is still ahead of it.
                assert bag.destination_id in self.reachable[belt_id], bag
                before = self.places.get(bag.id)
                if before is None:
                    # Admitted this tick, at the start of its input belt.
                    assert conveyor in engine.input_conveyors.values()
                    assert (bag.position_m, bag.entered_at_s) == (0, engine.time_s)
                    entered.setdefault(belt_id, []).append((bag, None))
                elif before[0] == belt_id:
                    moved = bag.position_m - before[1]
                    limit = 0 if belt_id in self.stopped else conveyor.config.speed_m_s * STEP_SECONDS
                    assert -EPSILON <= moved <= limit + EPSILON, bag
                else:
                    # One hop along the plant, to the belt chosen for this bag.
                    previous = engine.conveyors[before[0]]
                    assert previous.config.id not in self.stopped
                    assert engine._next_conveyor(previous, bag) is conveyor
                    assert bag.position_m == 0
                    entered.setdefault(belt_id, []).append((bag, previous))
        assert all(len(bags) == 1 for bags in entered.values())

        self.check_queues(entered)
        self.check_waiting_at_belt_ends(entered)
        self.check_merges(entered)
        self.remember()

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
            if conveyor.stopped or not conveyor.baggage or not at_end(conveyor, conveyor.baggage[-1]):
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
                assert conveyor.stopped or not waiting or not at_end(conveyor, waiting[0])


def with_rates(rate):
    layout = default_layout()
    return replace(layout, inputs=tuple(replace(node, arrival_rate_bags_s=rate)
                                        for node in layout.inputs))


def with_slow_branch_2():
    layout = default_layout()
    return replace(layout, belts=tuple(replace(belt, speed_m_s=0.1) if belt.id == "branch-2"
                                       else belt for belt in layout.belts))


# Layout, commands by tick, number of ticks.
SCENARIOS = {
    "normal flow": (default_layout(), {}, 12000),
    "saturated inputs": (with_rates(1), {}, 6000),
    "feeder B stopped for 120 s": (default_layout(), {
        2000: ("stop_belt", "feeder-b"), 4400: ("restart_belt", "feeder-b")}, 12000),
    "collector stopped for 60 s": (default_layout(), {
        3000: ("stop_belt", "collector"), 4200: ("restart_belt", "collector")}, 12000),
    "slow branch 2": (with_slow_branch_2(), {}, 6000),
}


def run(layout, commands, ticks, seed=42):
    engine = Engine(layout, seed=seed)
    checker = PlantChecker(engine)
    for tick in range(ticks):
        if tick in commands:
            method, belt_id = commands[tick]
            getattr(engine, method)(belt_id)
            checker.stopped = {belt_id for belt_id, conveyor in engine.conveyors.items()
                               if conveyor.stopped}
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


@pytest.mark.parametrize("sabotage", [unfair_merge, lazy_feeder, lazy_admission, wrong_branch])
def test_the_checker_notices_a_broken_rule(sabotage):
    engine = Engine(with_rates(1))
    checker = PlantChecker(engine)
    sabotage(engine)
    with pytest.raises(AssertionError):
        for _ in range(3000):
            engine.step()
            checker.check()
