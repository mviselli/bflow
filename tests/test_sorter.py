"""Predetermined branches at the sorter, and waiting when a branch has no space."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace

import pytest

from bflow.core.engine import Engine
from bflow.core.layout import default_layout, minimal_layout
from bflow.core.models import Baggage


BRANCHES = {"output-1": "branch-1-1", "output-2": "branch-2", "output-3": "branch-3-1"}


def quiet_engine():
    """An engine on the default plant with no arrivals."""
    layout = default_layout()
    inputs = tuple(replace(node, arrival_rate_bags_s=0) for node in layout.inputs)
    return Engine(replace(layout, inputs=inputs))


def place(engine, conveyor_id, name, destination_id, position):
    bag = Baggage(name, destination_id, 0.6, 0, conveyor_id, position, entered_at_s=0)
    engine.conveyors[conveyor_id].baggage.insert(0, bag)
    return bag


def test_each_output_is_reached_through_one_predetermined_branch():
    assert Engine(default_layout()).sorter_routes == {"sorter": BRANCHES}
    assert Engine(minimal_layout()).sorter_routes == {}


@pytest.mark.parametrize("destination_id, branch_id", BRANCHES.items())
def test_the_sorter_sends_a_bag_onto_the_branch_of_its_destination(destination_id, branch_id):
    engine = quiet_engine()
    bag = place(engine, "collector", "bag", destination_id, 11.4)
    engine.step()
    assert engine.conveyors["collector"].baggage == []
    assert engine.conveyors[branch_id].baggage == [bag]
    assert (bag.conveyor_id, bag.position_m) == (branch_id, 0)
    engine.step()
    assert bag.position_m == pytest.approx(0.05)


def test_a_bag_waits_at_the_sorter_while_its_branch_has_no_space():
    engine = quiet_engine()
    ahead = place(engine, "branch-2", "ahead", "output-2", 0)
    bag = place(engine, "collector", "bag", "output-2", 11.4)
    # Its branch is free, but it cannot overtake the waiting bag.
    behind = place(engine, "collector", "behind", "output-1", 10.6)
    for _ in range(15):
        engine.step()
        assert bag.conveyor_id == "collector"
        assert bag.position_m == 11.4
        assert behind.conveyor_id == "collector"
    # 16 ticks at 1 m/s give the bag length plus the gap on the branch.
    engine.step()
    assert ahead.position_m == pytest.approx(0.8)
    assert (bag.conveyor_id, bag.position_m) == ("branch-2", 0)
    # The bag behind reaches the end of the collector 0.8 m later.
    for _ in range(17):
        engine.step()
    assert behind.conveyor_id == "branch-1-1"


@pytest.mark.parametrize("offset, moved", [(-1e-9, False), (0, True)])
def test_a_branch_needs_the_bag_length_plus_the_gap(offset, moved):
    engine = quiet_engine()
    place(engine, "collector", "bag", "output-3", 11.4)
    place(engine, "branch-3-1", "ahead", "output-3", 0.6 + 0.2 + offset)
    leaving = engine._evaluate_transfers()
    assert (engine.conveyors["collector"] in leaving) == moved


def test_evaluation_at_the_sorter_is_read_only():
    engine = quiet_engine()
    place(engine, "collector", "bag", "output-1", 11.4)
    before = deepcopy(engine.conveyors)
    leaving = engine._evaluate_transfers()
    assert leaving == (engine.conveyors["collector"],)
    assert engine._evaluate_transfers() == leaving
    assert engine.conveyors == before


def test_the_full_plant_delivers_every_bag_to_its_destination():
    engine = Engine(default_layout())
    delivered = Counter()
    for _ in range(12000):
        engine.step()
        assert engine.stats().is_conserved
        delivered.update(bag.destination_id for bag in engine.exited_this_tick)
    assert engine.misdelivered_count == 0
    assert engine.correctly_delivered_count == sum(delivered.values()) > 400
    assert set(delivered) == set(BRANCHES)
    # 0.75 bags/s is below the capacity of every belt: nothing piles up.
    assert engine.waiting_count == 0
    assert engine.in_transit_count < 40


def test_a_slow_branch_blocks_the_sorter_and_the_queue_grows_upstream():
    layout = default_layout()
    # 0.1 m/s carries 0.125 bags/s; output 2 gets about 0.25 bags/s.
    belts = tuple(replace(belt, speed_m_s=0.1) if belt.id == "branch-2" else belt
                  for belt in layout.belts)
    engine = Engine(replace(layout, belts=belts))
    collector = engine.conveyors["collector"]
    blocked_ticks = 0
    for tick in range(1, 12001):
        engine.step()
        assert engine.stats().is_conserved
        front = collector.baggage[-1] if collector.baggage else None
        if (tick > 6000 and front is not None and front.destination_id == "output-2"
                and front.position_m == collector.config.length_m - front.length_m):
            blocked_ticks += 1
    assert engine.misdelivered_count == 0
    # Branch 2 frees the entry space for a bag every 160 ticks; in between,
    # the bags for the other outputs ahead of the next one for output 2 pass
    # in about 16 ticks each. So most of the time a bag for output 2 waits at
    # the sorter, holding up the others.
    assert blocked_ticks > 0.5 * 6000
    assert len(collector.baggage) >= 13
    assert engine.waiting_count > 100
    assert all(engine.waiting.values())
