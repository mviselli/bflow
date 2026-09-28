"""Belt occupancy, waiting per input and throughput in the last 60 seconds."""

from dataclasses import replace

import pytest

from bflow.core.engine import THROUGHPUT_WINDOW_TICKS, Engine
from bflow.core.layout import default_layout, minimal_layout
from bflow.core.models import Baggage
from bflow.core.stats import BeltStats


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def place(engine, conveyor_id, name, position, destination_id="output-1"):
    bag = Baggage(name, destination_id, 0.6, 0, conveyor_id, position, entered_at_s=0)
    engine.conveyors[conveyor_id].baggage.insert(0, bag)
    return bag


def test_capacity_is_the_most_bags_a_belt_holds_with_the_gap():
    engine = Engine(default_layout())
    # 0.6 m bags and 0.2 m gaps: 5 on 4 m, 10 on 8 m, 15 on 12 m.
    assert engine.belt_capacities == {
        "feeder-a-1": 10, "feeder-a-2": 5, "feeder-b": 10, "feeder-c-1": 10,
        "feeder-c-2": 5, "collector": 15, "branch-1-1": 5, "branch-1-2": 10,
        "branch-2": 10, "branch-3-1": 5, "branch-3-2": 10,
    }


@pytest.mark.parametrize("length, gap, capacity", [
    (1.4, 0.2, 2),         # exactly two bags and one gap
    (1.4 - 1e-6, 0.2, 1),  # just short of it
    (2.2, 0.2, 3),
    (1.8, 0, 3),           # no gap: three bags end to end
    (0.6, 0.2, 1),         # a belt as long as a bag
])
def test_an_exact_fit_is_not_lost_to_rounding(length, gap, capacity):
    engine = Engine(minimal_layout(length_m=length, min_gap_m=gap))
    assert engine.belt_capacities == {"belt-1": capacity}


def test_occupancy_is_the_share_of_the_capacity_in_layout_order():
    engine = Engine(default_layout())
    for index in range(3):
        place(engine, "feeder-a-2", f"bag-{index}", index * 0.8)
    belts = engine.stats().belts
    assert [belt.belt_id for belt in belts] == list(engine.conveyors)
    assert belts[1] == BeltStats("feeder-a-2", 3, 5)
    assert belts[1].occupancy == 0.6
    assert belts[0].occupancy == 0


def test_occupancy_reaches_one_and_never_exceeds_it_behind_a_stopped_branch():
    engine = Engine(default_layout())
    engine.stop_belt("branch-2")
    for _ in range(12000):
        engine.step()
        stats = engine.stats()
        assert stats.is_conserved
        assert all(belt.occupancy <= 1 for belt in stats.belts)
    full = {belt.belt_id for belt in stats.belts if belt.occupancy == 1}
    assert full == {"feeder-a-1", "feeder-a-2", "feeder-b", "feeder-c-1", "feeder-c-2",
                    "collector"}


def test_waiting_is_reported_for_each_input_in_layout_order():
    layout = default_layout()
    rates = (0.25, 10, 0.25)
    inputs = tuple(replace(node, arrival_rate_bags_s=rate)
                   for node, rate in zip(layout.inputs, rates, strict=True))
    engine = Engine(replace(layout, inputs=inputs))
    advance(engine, 200)
    stats = engine.stats()
    waiting = {node.input_id: node.waiting for node in stats.inputs}
    assert list(waiting) == ["input-a", "input-b", "input-c"]
    assert waiting["input-a"] == waiting["input-c"] == 0
    assert waiting["input-b"] == len(engine.waiting["input-b"]) == stats.waiting > 0
    assert stats.is_conserved


def test_a_correct_delivery_counts_for_exactly_sixty_seconds():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    place(engine, "belt-1", "bag", 9.4)
    engine.step()
    assert engine.correctly_delivered_count == 1
    assert THROUGHPUT_WINDOW_TICKS == 1200
    advance(engine, 1198)
    assert (engine.tick, engine.stats().throughput) == (1199, 1)
    engine.step()
    assert (engine.tick, engine.stats().throughput) == (1200, 1)
    engine.step()
    assert (engine.tick, engine.stats().throughput) == (1201, 0)


def test_throughput_counts_only_correct_deliveries():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    place(engine, "belt-1", "wrong", 9.4, destination_id="output-9")
    engine.step()
    stats = engine.stats()
    assert (stats.misdelivered, stats.throughput) == (1, 0)


def test_throughput_matches_the_demand_in_steady_flow_and_falls_behind_a_stop():
    engine = Engine(default_layout())
    advance(engine, 12000)
    # 0.75 bags/s for 60 s.
    assert engine.stats().throughput == 45
    engine.stop_belt("collector")
    advance(engine, 1200)
    # The branches empty within a minute; then nothing reaches an output.
    assert engine.stats().throughput < 10
    advance(engine, 1200)
    assert engine.stats().throughput == 0


def test_the_new_indicators_are_part_of_a_frozen_snapshot():
    engine = Engine(default_layout())
    advance(engine, 4000)
    stats = engine.stats()
    belts, inputs, throughput = stats.belts, stats.inputs, stats.throughput
    advance(engine, 400)
    assert (stats.belts, stats.inputs, stats.throughput) == (belts, inputs, throughput)
    assert engine.stats() != stats
