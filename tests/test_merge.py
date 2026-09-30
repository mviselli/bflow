"""Alternation at the merge between the belts that have a bag ready."""

from copy import deepcopy
from dataclasses import replace

import pytest

from bflow.core.engine import Engine
from bflow.core.layout import OutputConfig, Point, default_layout
from bflow.core.models import Baggage
from tests.layouts import compact_layout


FEEDERS = ("feeder-a-2", "feeder-b", "feeder-c-2")


def quiet_engine(layout=None):
    """An engine on the compact plant (or another one) with no arrivals."""
    layout = layout or compact_layout()
    inputs = tuple(replace(node, arrival_rate_bags_s=0) for node in layout.inputs)
    return Engine(replace(layout, inputs=inputs))


def queue_at_merge(engine, conveyor_id, count):
    """Puts ``count`` spaced bags at the end of a belt, the first touching the merge."""
    conveyor = engine.conveyors[conveyor_id]
    for index in reversed(range(count)):
        position = conveyor.config.length_m - 0.6 - index * 0.8
        bag = Baggage(f"{conveyor_id}-{index}", "output-1", 0.6, 0,
                      conveyor_id, position, entered_at_s=0)
        conveyor.baggage.append(bag)


def merge_order(engine, ticks):
    """The source belt of each bag entering the collector, in order of arrival."""
    order = []
    for _ in range(ticks):
        engine.step()
        collector = engine.conveyors["collector"].baggage
        if collector and collector[0].position_m == 0:
            order.append(collector[0].id.rsplit("-", 1)[0])
    return order


def test_ready_belts_take_turns_in_layout_order():
    engine = quiet_engine()
    for feeder in FEEDERS:
        queue_at_merge(engine, feeder, 2)
    assert merge_order(engine, 200) == list(FEEDERS) * 2


def test_the_first_bag_through_the_merge_does_not_move_again_in_the_same_tick():
    engine = quiet_engine()
    for feeder in FEEDERS:
        queue_at_merge(engine, feeder, 1)
    engine.step()
    (bag,) = engine.conveyors["collector"].baggage
    assert (bag.id, bag.conveyor_id, bag.position_m) == ("feeder-a-2-0", "collector", 0)
    assert engine.last_merged == {"merge": "feeder-a-2"}
    # The others wait at the end of their belt, unmoved.
    for feeder in FEEDERS[1:]:
        (waiting,) = engine.conveyors[feeder].baggage
        assert waiting.position_m == engine.conveyors[feeder].config.length_m - 0.6
    engine.step()
    assert bag.position_m == pytest.approx(0.05)


def test_a_belt_with_nothing_ready_loses_its_turn():
    engine = quiet_engine()
    queue_at_merge(engine, "feeder-a-2", 3)
    queue_at_merge(engine, "feeder-c-2", 3)
    assert merge_order(engine, 200) == ["feeder-a-2", "feeder-c-2"] * 3


def test_a_belt_alone_at_the_merge_never_waits_for_a_turn():
    engine = quiet_engine()
    queue_at_merge(engine, "feeder-b", 3)
    # Its own turn has just been used, and the other belts are empty.
    engine.last_merged["merge"] = "feeder-b"
    for _ in range(100):
        engine.step()
        # Never left ready at the end of its belt with space on the collector.
        assert not engine._resolve_merges(engine._evaluate_transfers())
    assert [bag.id for bag in engine.conveyors["collector"].baggage] == [
        "feeder-b-2", "feeder-b-1", "feeder-b-0"]


def test_the_turn_continues_after_the_last_belt_let_through_and_wraps_around():
    engine = quiet_engine()
    for feeder in FEEDERS:
        queue_at_merge(engine, feeder, 1)
    engine.last_merged["merge"] = "feeder-b"
    assert merge_order(engine, 100) == ["feeder-c-2", "feeder-a-2", "feeder-b"]


def test_resolution_is_read_only_and_keeps_one_belt_per_merge():
    engine = quiet_engine()
    for feeder in FEEDERS:
        queue_at_merge(engine, feeder, 1)
    before = deepcopy(engine.conveyors)
    ready = engine._evaluate_transfers()
    assert [conveyor.config.id for conveyor in ready] == list(FEEDERS)
    chosen = engine._resolve_merges(ready)
    assert [conveyor.config.id for conveyor in chosen] == ["feeder-a-2"]
    assert engine._resolve_merges(ready) == chosen
    assert engine.conveyors == before
    assert engine.last_merged == {"merge": None}


@pytest.mark.parametrize("offset, moved", [(-1e-9, False), (0, True)])
def test_the_merge_needs_the_bag_length_plus_the_gap_on_the_collector(offset, moved):
    engine = quiet_engine()
    queue_at_merge(engine, "feeder-b", 1)
    ahead = Baggage("ahead", "output-1", 0.6, 0, "collector", 0.6 + 0.2 + offset,
                    entered_at_s=0)
    engine.conveyors["collector"].baggage.append(ahead)
    chosen = engine._resolve_merges(engine._evaluate_transfers())
    assert (engine.conveyors["feeder-b"] in chosen) == moved


def merge_to_one_output():
    """Three inputs → merge → collector → one output: the merge with nothing after it."""
    layout = compact_layout()
    output = OutputConfig("output-1", "BF 101", Point(20, 4))
    belts = layout.belts[:5] + (replace(layout.belts[5], target_id="output-1"),)
    return replace(layout, sorters=(), outputs=(output,), belts=belts)


def test_a_saturated_merge_lets_the_belts_through_in_strict_rotation():
    layout = merge_to_one_output()
    # 3 bags/s offered, 1.25 bags/s through the collector: every feeder queues.
    inputs = tuple(replace(node, arrival_rate_bags_s=1) for node in layout.inputs)
    engine = Engine(replace(layout, inputs=inputs))
    merged = []
    for _ in range(12000):
        engine.step()
        assert engine.stats().is_conserved
        collector = engine.conveyors["collector"].baggage
        if collector and collector[0].position_m == 0:
            merged.append(engine.last_merged["merge"])
    # Input B is 4 m closer to the merge: its first bags pass alone.
    assert merged[:4] == ["feeder-b"] * 4
    # Then all three are always ready, and each gets one bag in three.
    rotation = merged[4:7]
    assert sorted(rotation) == sorted(FEEDERS)
    assert merged[4:] == [rotation[i % 3] for i in range(len(merged) - 4)]
    assert len(merged) > 700
    assert all(engine.waiting.values())


def test_below_capacity_the_merge_lets_every_bag_through():
    engine = Engine(merge_to_one_output(), seed=7)
    for _ in range(12000):
        engine.step()
    assert engine.waiting_count == 0
    assert engine.generated_count == 450
    assert engine.correctly_delivered_count + engine.in_transit_count == 450
    assert engine.in_transit_count < 20


def test_a_belt_leaving_a_merge_can_turn_a_corner():
    # In the demo plant island B's collector leaves merge-b3 and turns up
    # towards the line: the belts entering merge-b3 hand over to it.
    engine = quiet_engine(default_layout())
    for belt_id in ("island-b-2", "feeder-b3"):
        conveyor = engine.conveyors[belt_id]
        bag = Baggage(id=f"bag-{belt_id}", destination_id="output-1", length_m=0.6,
                      generated_at_s=0, conveyor_id=belt_id, entered_at_s=0,
                      position_m=conveyor.config.length_m - 0.6)
        conveyor.baggage.append(bag)
        engine.admitted_count += 1
    engine.step()
    assert [bag.id for bag in engine.conveyors["island-b-3"].baggage] == ["bag-island-b-2"]
    for _ in range(40):
        engine.step()
    assert [bag.id for bag in engine.conveyors["island-b-3"].baggage][-1] == "bag-island-b-2"
    assert engine.conveyors["feeder-b3"].baggage == []
