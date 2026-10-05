"""Prolonged wait: a bag on a belt that has not advanced for 30 simulated seconds.

The warning starts once per occurrence and resolves when the bag advances
again (moving, passing to the next belt or exiting). The bag is never
removed: it stays in transit where it is. Bags queued at a desk are not on
a belt and have their own entrance-queue events.
"""

from dataclasses import replace

import pytest

from bflow.core.engine import PROLONGED_WAIT_S, Engine
from bflow.core.events import Severity
from bflow.core.layout import minimal_layout
from bflow.core.models import Baggage
from tests.layouts import compact_layout


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def place(engine, conveyor_id, name, position, destination_id="output-1"):
    bag = Baggage(name, destination_id, engine.layout.baggage_length_m, 0, conveyor_id, position,
                  entered_at_s=0)
    engine.conveyors[conveyor_id].baggage.insert(0, bag)
    engine.generated_count += 1  # keeps the counters consistent for stats()
    engine.admitted_count += 1
    return bag


def wait_events(engine):
    return [(event.tick, event.severity, event.kind, event.element_id, event.baggage_id)
            for event in engine.events.recent if event.kind.startswith("prolonged_wait")]


def quiet_compact():
    layout = compact_layout()
    return Engine(replace(layout, inputs=tuple(replace(node, arrival_rate_bags_s=0)
                                               for node in layout.inputs)))


def test_a_bag_held_still_warns_after_exactly_30_seconds_and_stays_in_transit():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 2.0)
    engine.stop_belt("belt-1")
    assert PROLONGED_WAIT_S == 30
    advance(engine, 599)
    assert not bag.prolonged_wait
    engine.step()  # 30.00 s since its admission at 0
    assert bag.prolonged_wait
    assert wait_events(engine) == [
        (600, Severity.WARNING, "prolonged_wait_started", "belt-1", "bag")]
    advance(engine, 2000)
    stats = engine.stats()
    # One warning however long it waits; the bag is still on its belt.
    assert stats.warnings == 1
    assert (bag.conveyor_id, bag.position_m, stats.in_transit) == ("belt-1", 2.0, 1)
    assert stats.is_conserved


def test_the_wait_resolves_when_the_bag_moves_again():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 2.0)
    engine.stop_belt("belt-1")
    advance(engine, 700)
    engine.restart_belt("belt-1")
    engine.step()
    assert not bag.prolonged_wait
    assert bag.moved_at_s == 35.05
    assert wait_events(engine)[-1] == (
        701, Severity.INFO, "prolonged_wait_resolved", "belt-1", "bag")
    assert engine.events.recent[-1].message == "Moving again after 35.0 s"
    # The resolution is information: still one warning.
    assert engine.stats().warnings == 1


def test_the_wait_resolves_when_the_bag_exits():
    engine = Engine(minimal_layout(length_m=6, arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 5.4)  # front edge at the end
    engine.fault_belt("belt-1")
    advance(engine, 600)
    assert bag.prolonged_wait
    engine.repair_belt("belt-1")
    engine.step()
    assert bag.exited_at_s == 30.05 and not bag.prolonged_wait
    assert [kind for _, _, kind, _, _ in wait_events(engine)] == [
        "prolonged_wait_started", "prolonged_wait_resolved"]


def test_a_bag_waiting_for_space_on_a_running_belt_warns_too():
    # Branch 2 is stopped and holds a bag at its entrance: the bag for output 2
    # waits at the end of the running collector, and the bag behind it waits
    # at the minimum gap.
    engine = quiet_compact()
    engine.stop_belt("branch-2")
    place(engine, "branch-2", "blocker", 0.0, "output-2")
    length = engine.conveyors["collector"].config.length_m
    front = place(engine, "collector", "front", length - 0.6, "output-2")
    behind = place(engine, "collector", "behind", length - 1.4, "output-3")
    advance(engine, 600)
    assert front.prolonged_wait and behind.prolonged_wait
    assert not engine.conveyors["collector"].halted
    assert {bag_id for *_, bag_id in wait_events(engine)} == {"blocker", "front", "behind"}


def test_a_slow_bag_that_keeps_advancing_never_warns():
    engine = Engine(minimal_layout(speed_m_s=0.01, arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 0.0)
    advance(engine, 6000)  # 300 s at 0.5 mm per tick
    assert bag.position_m > 2.9
    assert not bag.prolonged_wait
    assert wait_events(engine) == []


def test_bags_queued_at_a_desk_are_not_on_a_belt_and_do_not_warn():
    engine = Engine(minimal_layout(arrival_rate_bags_s=1))
    engine.stop_belt("belt-1")
    advance(engine, 2000)
    assert engine.waiting_count > 90
    # Only the bag admitted at the stopped belt's free entrance warns.
    assert [bag_id for *_, bag_id in wait_events(engine)] == ["bag-1"]


def test_a_second_wait_after_moving_is_a_new_warning():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 2.0)
    engine.stop_belt("belt-1")
    advance(engine, 600)
    engine.restart_belt("belt-1")
    engine.step()
    engine.stop_belt("belt-1")
    advance(engine, 599)
    assert not bag.prolonged_wait
    engine.step()
    assert bag.prolonged_wait
    assert [tick for tick, *_ in wait_events(engine)] == [600, 601, 1201]
    assert engine.stats().warnings == 2


def test_a_bag_cannot_move_before_its_admission():
    with pytest.raises(ValueError, match="before its admission"):
        Baggage("bag", "output-1", 0.6, 0, "belt-1", 0, entered_at_s=5, moved_at_s=4)
