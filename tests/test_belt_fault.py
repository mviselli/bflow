"""Belt fault and repair: a fault halts a belt until it is repaired.

Unlike the operator's stop, a fault is an error, and restarting the belt
does not clear it. The stop and the fault are independent conditions.
"""

import pytest

from bflow.core.engine import Engine
from bflow.core.events import Severity
from bflow.core.layout import minimal_layout
from bflow.core.models import Baggage
from tests.layouts import compact_layout


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def place(engine, conveyor_id, name, position):
    bag = Baggage(name, "output-1", 0.6, 0, conveyor_id, position, entered_at_s=0)
    engine.conveyors[conveyor_id].baggage.insert(0, bag)
    return bag


def belt_events(engine):
    return [(event.tick, event.severity, event.kind, event.element_id)
            for event in engine.events.recent if event.kind.startswith("belt_")]


def test_a_faulty_belt_does_not_move_its_bags_until_repaired():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 2.0)
    engine.fault_belt("belt-1")
    # The command changes nothing until the next step.
    assert (engine.tick, bag.position_m) == (0, 2.0)
    advance(engine, 100)
    assert bag.position_m == 2.0
    engine.repair_belt("belt-1")
    engine.step()
    assert bag.position_m == pytest.approx(2.05)


def test_a_faulty_belt_does_not_deliver_but_still_admits_at_its_free_entrance():
    engine = Engine(minimal_layout(length_m=6, arrival_rate_bags_s=1))
    front = place(engine, "belt-1", "front", 5.4)  # front edge at the end of the belt
    engine.fault_belt("belt-1")
    advance(engine, 100)
    assert front.exited_at_s is None
    # The first arrival is admitted at position 0 and stays there.
    assert [bag.position_m for bag in engine.conveyors["belt-1"].baggage] == [0.0, 5.4]
    assert engine.waiting_count > 0


def test_restart_does_not_clear_a_fault():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 2.0)
    engine.fault_belt("belt-1")
    engine.restart_belt("belt-1")
    advance(engine, 20)
    assert bag.position_m == 2.0
    assert engine.conveyors["belt-1"].faulty
    # Restarting a belt that was never stopped records nothing.
    assert [kind for _, _, kind, _ in belt_events(engine)] == ["belt_fault"]


def test_a_belt_stopped_during_a_fault_stays_stopped_after_the_repair():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 2.0)
    engine.fault_belt("belt-1")
    engine.stop_belt("belt-1")
    engine.repair_belt("belt-1")
    advance(engine, 20)
    assert bag.position_m == 2.0
    engine.restart_belt("belt-1")
    engine.step()
    assert bag.position_m == pytest.approx(2.05)


def test_repair_does_not_restart_a_stopped_belt_and_restart_does_not_repair():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    conveyor = engine.conveyors["belt-1"]
    engine.stop_belt("belt-1")
    engine.fault_belt("belt-1")
    engine.restart_belt("belt-1")
    assert (conveyor.stopped, conveyor.faulty, conveyor.halted) == (False, True, True)
    engine.repair_belt("belt-1")
    assert (conveyor.stopped, conveyor.faulty, conveyor.halted) == (False, False, False)


def test_a_fault_counts_one_error_and_the_repair_is_information():
    engine = Engine(compact_layout())
    advance(engine, 20)
    engine.fault_belt("collector")
    engine.fault_belt("collector")
    advance(engine, 20)
    engine.repair_belt("collector")
    engine.repair_belt("collector")
    engine.repair_belt("feeder-b")
    assert belt_events(engine) == [
        (20, Severity.ERROR, "belt_fault", "collector"),
        (40, Severity.INFO, "belt_repaired", "collector"),
    ]
    stats = engine.stats()
    assert (stats.errors, stats.warnings) == (1, 0)
    # A second fault on the same belt is a new occurrence.
    engine.fault_belt("collector")
    assert engine.stats().errors == 2


@pytest.mark.parametrize("command", ["fault_belt", "repair_belt"])
def test_an_unknown_belt_is_rejected(command):
    engine = Engine(compact_layout())
    with pytest.raises(ValueError, match="Unknown belt"):
        getattr(engine, command)("output-1")


def test_the_same_faults_at_the_same_ticks_give_the_same_run():
    def run():
        engine = Engine(compact_layout(), seed=5)
        for tick in range(3000):
            if tick == 500:
                engine.fault_belt("collector")
            if tick == 900:
                engine.restart_belt("collector")
            if tick == 1500:
                engine.repair_belt("collector")
            engine.step()
        bags = [(bag.id, bag.conveyor_id, bag.position_m)
                for conveyor in engine.conveyors.values() for bag in conveyor.baggage]
        return engine.stats(), bags, [event.kind for event in engine.events.recent]

    assert run() == run()
