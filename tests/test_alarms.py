"""Alarms: lasting conditions that are active, acknowledged and resolved.

A belt fault, a congestion and a prolonged wait each open one alarm when
they start and resolve it when they end. Acknowledging an alarm only records
that the operator has seen it: the device is not repaired.
"""

import pytest

from bflow.core.engine import MAX_RESOLVED_ALARMS, Engine
from bflow.core.events import AlarmState, Severity
from bflow.core.layout import minimal_layout
from bflow.core.models import Baggage


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def place(engine, name, position, conveyor_id="belt-1"):
    bag = Baggage(name, "output-1", 0.6, 0, conveyor_id, position, entered_at_s=0)
    engine.conveyors[conveyor_id].baggage.insert(0, bag)
    return bag


def alarm_events(engine):
    return [(event.tick, event.kind, event.alarm_id) for event in engine.events.recent
            if event.alarm_id is not None]


def test_a_fault_opens_an_active_error_alarm_and_the_repair_resolves_it():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    advance(engine, 10)
    engine.fault_belt("belt-1")
    [alarm] = engine.alarms.values()
    assert (alarm.id, alarm.kind, alarm.severity, alarm.state) == (
        1, "belt_fault", Severity.ERROR, AlarmState.ACTIVE)
    assert (alarm.element_id, alarm.baggage_id, alarm.raised_at_s) == ("belt-1", None, 0.5)
    advance(engine, 10)
    engine.repair_belt("belt-1")
    assert engine.alarms == {}
    assert list(engine.resolved_alarms) == [alarm]
    assert (alarm.state, alarm.acknowledged_at_s, alarm.resolved_at_s) == (
        AlarmState.RESOLVED, None, 1.0)
    assert alarm_events(engine) == [(10, "belt_fault", 1), (20, "belt_repaired", 1)]


def test_acknowledging_a_fault_does_not_repair_the_belt():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    bag = place(engine, "bag", 2.0)
    engine.fault_belt("belt-1")
    advance(engine, 5)
    engine.acknowledge_alarm(1)
    alarm = engine.alarms[1]
    assert (alarm.state, alarm.acknowledged_at_s) == (AlarmState.ACKNOWLEDGED, 0.25)
    advance(engine, 100)
    # Still faulty, still halted, the alarm still open.
    assert engine.conveyors["belt-1"].faulty
    assert bag.position_m == 2.0
    assert engine.alarms == {1: alarm}
    engine.repair_belt("belt-1")
    assert alarm.state is AlarmState.RESOLVED
    # Resolving keeps the acknowledgement time.
    assert (alarm.acknowledged_at_s, alarm.resolved_at_s) == (0.25, 5.25)


def test_an_acknowledgement_is_one_info_event_and_counts_nothing():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    engine.fault_belt("belt-1")
    engine.step()
    engine.acknowledge_alarm(1)
    engine.acknowledge_alarm(1)
    [event] = [event for event in engine.events.recent if event.kind == "alarm_acknowledged"]
    assert (event.tick, event.severity, event.element_id, event.alarm_id) == (
        1, Severity.INFO, "belt-1", 1)
    assert event.message == "Alarm acknowledged: Belt fault: halted until repaired"
    assert (engine.stats().errors, engine.stats().warnings) == (1, 0)
    # Acknowledging after the resolution does nothing either.
    engine.repair_belt("belt-1")
    engine.acknowledge_alarm(1)
    assert [kind for _, kind, _ in alarm_events(engine)] == [
        "belt_fault", "alarm_acknowledged", "belt_repaired"]


@pytest.mark.parametrize("alarm_id", [0, 2, -1, True, 1.0, "1"])
def test_an_alarm_never_raised_is_refused(alarm_id):
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    engine.fault_belt("belt-1")
    with pytest.raises(ValueError, match="Unknown alarm"):
        engine.acknowledge_alarm(alarm_id)


def test_a_second_fault_is_a_new_alarm_with_the_next_id():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    engine.fault_belt("belt-1")
    engine.fault_belt("belt-1")
    assert list(engine.alarms) == [1]
    engine.repair_belt("belt-1")
    engine.fault_belt("belt-1")
    assert list(engine.alarms) == [2]
    assert engine.last_alarm_id == 2
    assert engine.alarms[2].state is AlarmState.ACTIVE


def test_congestion_opens_a_warning_alarm_for_the_belt_until_it_clears():
    # A stopped minimal belt of capacity 12 holding 10 bags: 83 % for 10 s.
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    engine.stop_belt("belt-1")
    bags = [place(engine, f"bag-{n}", n * 0.9) for n in range(10)]
    advance(engine, 201)
    [alarm] = engine.alarms.values()
    assert (alarm.kind, alarm.severity, alarm.element_id, alarm.raised_at_s) == (
        "congestion", Severity.WARNING, "belt-1", 10.05)
    engine.acknowledge_alarm(alarm.id)
    # Three bags gone: 7 of 12 is below 60 %.
    for bag in bags[:3]:
        engine.conveyors["belt-1"].baggage.remove(bag)
    engine.step()
    assert alarm.id not in engine.alarms
    assert (alarm.state, alarm.resolved_at_s) == (AlarmState.RESOLVED, 10.1)


def test_each_bag_in_a_prolonged_wait_has_its_own_alarm_resolved_when_it_moves():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    engine.stop_belt("belt-1")
    first, second = place(engine, "first", 4.0), place(engine, "second", 1.0)
    advance(engine, 600)
    # Raised in belt order, from the entrance.
    assert [(alarm.id, alarm.kind, alarm.baggage_id, alarm.element_id)
            for alarm in engine.alarms.values()] == [
        (1, "prolonged_wait", "second", "belt-1"), (2, "prolonged_wait", "first", "belt-1")]
    engine.acknowledge_alarm(2)
    engine.restart_belt("belt-1")
    engine.step()
    assert engine.alarms == {}
    # Resolved as they move, from the exit.
    assert [(alarm.baggage_id, alarm.acknowledged_at_s, alarm.resolved_at_s)
            for alarm in engine.resolved_alarms] == [("first", 30.0, 30.05),
                                                    ("second", None, 30.05)]
    assert not (first.prolonged_wait or second.prolonged_wait)


def test_a_prolonged_wait_resolved_by_the_exit_closes_its_alarm():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    front = place(engine, "front", engine.conveyors["belt-1"].config.length_m - 0.6)
    engine.fault_belt("belt-1")
    advance(engine, 600)
    assert {alarm.kind for alarm in engine.alarms.values()} == {"belt_fault", "prolonged_wait"}
    engine.repair_belt("belt-1")
    engine.step()
    assert front.exited_at_s == 30.05
    assert engine.alarms == {}
    assert [alarm.kind for alarm in engine.resolved_alarms] == ["belt_fault", "prolonged_wait"]


def test_alarm_times_are_simulated_so_without_steps_they_stand_still():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    advance(engine, 40)
    engine.fault_belt("belt-1")
    # A pause is the absence of steps: neither the alarm nor the time changes.
    alarm = engine.alarms[1]
    assert engine.time_s - alarm.raised_at_s == 0
    advance(engine, 20)
    assert engine.time_s - alarm.raised_at_s == 1.0


def test_only_the_latest_resolved_alarms_are_kept():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    for _ in range(MAX_RESOLVED_ALARMS + 5):
        engine.fault_belt("belt-1")
        engine.repair_belt("belt-1")
    assert len(engine.resolved_alarms) == MAX_RESOLVED_ALARMS
    assert engine.resolved_alarms[0].id == 6
    assert engine.resolved_alarms[-1].id == engine.last_alarm_id == MAX_RESOLVED_ALARMS + 5
    # Every occurrence is still counted.
    assert engine.stats().errors == MAX_RESOLVED_ALARMS + 5


def test_a_new_engine_starts_without_alarms():
    engine = Engine(minimal_layout())
    assert (engine.alarms, list(engine.resolved_alarms), engine.last_alarm_id) == ({}, [], 0)
