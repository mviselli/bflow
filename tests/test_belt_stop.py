"""Operational stop and restart of a single belt, distinct from the global pause."""

from dataclasses import replace

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


def quiet_plant():
    layout = compact_layout()
    inputs = tuple(replace(node, arrival_rate_bags_s=0) for node in layout.inputs)
    return Engine(replace(layout, inputs=inputs))


def test_a_stopped_belt_does_not_move_its_bags_until_restarted():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 2.0)
    engine.stop_belt("belt-1")
    # The command changes nothing until the next step.
    assert (engine.tick, bag.position_m) == (0, 2.0)
    advance(engine, 100)
    assert bag.position_m == 2.0
    engine.restart_belt("belt-1")
    engine.step()
    assert bag.position_m == pytest.approx(2.05)


def test_a_stopped_belt_does_not_deliver_to_its_output():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "belt-1", "bag", 9.4)
    engine.stop_belt("belt-1")
    advance(engine, 50)
    assert engine.exited_count == 0
    assert bag.conveyor_id == "belt-1"
    engine.restart_belt("belt-1")
    engine.step()
    assert engine.exited_this_tick == (bag,)
    assert engine.correctly_delivered_count == 1


def test_a_stopped_input_belt_admits_one_bag_at_its_free_entrance_and_keeps_it():
    engine = Engine(minimal_layout(arrival_rate_bags_s=1))
    engine.stop_belt("belt-1")
    advance(engine, 200)
    (bag,) = engine.conveyors["belt-1"].baggage
    assert (bag.id, bag.position_m, bag.entered_at_s) == ("bag-1", 0, 1)
    assert engine.generated_count == 10
    assert engine.waiting_count == 9
    assert engine.stats().is_conserved


def test_a_stopped_belt_receives_a_bag_only_when_its_entrance_has_space():
    engine = quiet_plant()
    engine.stop_belt("feeder-a-2")
    first = place(engine, "feeder-a-1", "first", 7.4)
    second = place(engine, "feeder-a-1", "second", 6.6)
    advance(engine, 100)
    assert (first.conveyor_id, first.position_m) == ("feeder-a-2", 0)
    # The first bag blocks the entrance: the second waits at the end of feeder-a-1.
    assert (second.conveyor_id, second.position_m) == ("feeder-a-1", 7.4)


def test_a_stopped_branch_holds_up_only_bags_behind_it():
    engine = quiet_plant()
    engine.stop_belt("branch-2")
    held = place(engine, "branch-2", "held", 1.0)
    passing = Baggage("passing", "output-3", 0.6, 0, "branch-3-2", 7.0, entered_at_s=0)
    engine.conveyors["branch-3-2"].baggage.append(passing)
    advance(engine, 40)
    assert held.position_m == 1.0
    assert passing.exited_at_s is not None


def test_stop_and_restart_record_one_info_event_each_and_repeats_are_no_ops():
    engine = Engine(compact_layout())
    advance(engine, 20)
    engine.stop_belt("collector")
    engine.stop_belt("collector")
    advance(engine, 20)
    engine.restart_belt("collector")
    engine.restart_belt("collector")
    engine.restart_belt("feeder-b")
    events = [(event.tick, event.severity, event.kind, event.element_id)
              for event in engine.events.recent if event.kind.startswith("belt_")]
    assert events == [
        (20, Severity.INFO, "belt_stopped", "collector"),
        (40, Severity.INFO, "belt_restarted", "collector"),
    ]
    stats = engine.stats()
    assert (stats.errors, stats.warnings) == (0, 0)


@pytest.mark.parametrize("command", ["stop_belt", "restart_belt"])
def test_an_unknown_belt_is_rejected(command):
    engine = Engine(compact_layout())
    with pytest.raises(ValueError, match="Unknown belt"):
        getattr(engine, command)("output-1")


def test_stopping_a_feeder_queues_its_input_while_the_plant_runs_and_restart_clears_it():
    engine = Engine(compact_layout())

    def run_until(tick):
        while engine.tick < tick:
            engine.step()
            assert engine.stats().is_conserved

    run_until(2000)
    engine.stop_belt("feeder-b")
    delivered_at_stop = engine.correctly_delivered_count
    run_until(4400)
    # 120 s stopped: input B builds a queue; A and C keep delivering.
    assert len(engine.waiting["input-b"]) > 20
    assert not engine.waiting["input-a"] and not engine.waiting["input-c"]
    assert engine.correctly_delivered_count > delivered_at_stop + 30
    engine.restart_belt("feeder-b")
    run_until(12000)
    # Demand is below capacity: the queue clears after the restart.
    assert engine.waiting_count == 0
    assert engine.misdelivered_count == 0


def test_the_same_commands_at_the_same_ticks_give_the_same_run():
    def run():
        engine = Engine(compact_layout(), seed=5)
        for tick in range(3000):
            if tick == 500:
                engine.stop_belt("collector")
            if tick == 1500:
                engine.restart_belt("collector")
            engine.step()
        bags = [(bag.id, bag.conveyor_id, bag.position_m)
                for conveyor in engine.conveyors.values() for bag in conveyor.baggage]
        return engine.stats(), bags, [event.kind for event in engine.events.recent]

    assert run() == run()
