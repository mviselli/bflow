"""Browser messages: strict command validation, snapshots faithful to the engine."""

import json

import pytest
from pydantic import ValidationError

from bflow.core.engine import STEP_MS, Engine
from bflow.core.events import Severity
from bflow.core.layout import default_layout, minimal_layout
from bflow.server.protocol import (
    AcknowledgeAlarmCommand,
    CommandRecord,
    ErrorMessage,
    FaultBeltCommand,
    ForceMissortCommand,
    RepairBeltCommand,
    ResetCommand,
    RestartBeltCommand,
    SetMissortProbabilityCommand,
    SetRateCommand,
    SetSpeedCommand,
    StopBeltCommand,
    LayoutMessage,
    PauseCommand,
    SnapshotMessage,
    StartCommand,
    StatsState,
    layout_message,
    parse_command,
    snapshot_message,
)


def run(engine: Engine, ticks: int) -> Engine:
    for _ in range(ticks):
        engine.step()
    return engine


# Commands


@pytest.mark.parametrize(("raw", "expected"), [
    ('{"type": "start"}', StartCommand),
    ('{"type": "pause"}', PauseCommand),
    (b'{"type": "pause"}', PauseCommand),
    ('{"type": "reset"}', ResetCommand),
    ('{"type": "set_speed", "speed": 5}', SetSpeedCommand),
    ('{"type": "set_rate", "input_id": "input-a1", "rate_bags_s": 0.25}', SetRateCommand),
    ('{"type": "set_rate", "input_id": "input-a1", "rate_bags_s": 0}', SetRateCommand),
    ('{"type": "stop_belt", "belt_id": "line-2"}', StopBeltCommand),
    ('{"type": "restart_belt", "belt_id": "line-2"}', RestartBeltCommand),
    ('{"type": "fault_belt", "belt_id": "line-2"}', FaultBeltCommand),
    ('{"type": "repair_belt", "belt_id": "line-2"}', RepairBeltCommand),
    ('{"type": "set_missort_probability", "probability": 0.1}', SetMissortProbabilityCommand),
    ('{"type": "set_missort_probability", "probability": 1}', SetMissortProbabilityCommand),
    ('{"type": "force_missort"}', ForceMissortCommand),
    ('{"type": "acknowledge_alarm", "alarm_id": 3}', AcknowledgeAlarmCommand),
])
def test_known_commands_are_parsed(raw, expected):
    assert isinstance(parse_command(raw), expected)


@pytest.mark.parametrize("raw", [
    '{"type": "explode"}',
    '{"type": "start", "speed": 2}',
    '{"command": "start"}',
    '{}',
    '"start"',
    '[{"type": "start"}]',
    '{"type": "start"',
    '',
    '{"type": "set_speed", "speed": 3}',
    '{"type": "set_speed", "speed": "5"}',
    '{"type": "set_speed"}',
    '{"type": "set_rate", "input_id": "input-a1", "rate_bags_s": -0.1}',
    '{"type": "set_rate", "input_id": "input-a1", "rate_bags_s": 1.5}',
    '{"type": "set_rate", "input_id": "", "rate_bags_s": 0.1}',
    '{"type": "set_rate", "rate_bags_s": 0.1}',
    '{"type": "stop_belt"}',
    '{"type": "stop_belt", "belt_id": "line-2", "now": true}',
    '{"type": "fault_belt"}',
    '{"type": "repair_belt", "belt_id": ""}',
    '{"type": "set_missort_probability", "probability": 1.1}',
    '{"type": "set_missort_probability", "probability": -0.5}',
    '{"type": "set_missort_probability"}',
    '{"type": "force_missort", "bag": "bag-1"}',
    '{"type": "reset", "seed": 7}',
    '{"type": "acknowledge_alarm"}',
    '{"type": "acknowledge_alarm", "alarm_id": 0}',
    '{"type": "acknowledge_alarm", "alarm_id": 1.5}',
    '{"type": "acknowledge_alarm", "alarm_id": "1"}',
    '{"type": "acknowledge_alarm", "alarm_id": 1, "all": true}',
])
def test_invalid_commands_are_rejected(raw):
    with pytest.raises(ValidationError):
        parse_command(raw)


def test_commands_are_immutable():
    command = parse_command('{"type": "start"}')
    with pytest.raises(ValidationError):
        command.type = "pause"


# Tick and simulated time


def test_initial_layout_describes_the_minimal_route():
    layout = layout_message(Engine())
    assert layout.model_dump() == {
        "type": "layout",
        "tick": 0,
        "time_s": 0.0,
        "step_ms": STEP_MS,
        "inputs": [{"id": "input-a", "label": "A", "position": {"x_m": 0.0, "y_m": 0.0}}],
        "merges": [],
        "sorters": [],
        "outputs": [{"id": "output-1", "label": "BF 101", "position": {"x_m": 10.0, "y_m": 0.0}}],
        "belts": [{
            "id": "belt-1", "source_id": "input-a", "target_id": "output-1",
            "start": {"x_m": 0.0, "y_m": 0.0}, "end": {"x_m": 10.0, "y_m": 0.0},
            "length_m": 10.0, "speed_m_s": 1.0,
        }],
        "baggage_length_m": 0.6,
        "min_gap_m": 0.2,
    }


def test_layout_follows_a_custom_configuration():
    config = minimal_layout(length_m=4.0, speed_m_s=0.5, baggage_length_m=0.8, min_gap_m=0.0)
    layout = layout_message(run(Engine(config), 3))
    assert (layout.tick, layout.time_s) == (3, 0.15)
    assert (layout.belts[0].length_m, layout.belts[0].speed_m_s) == (4.0, 0.5)
    assert (layout.baggage_length_m, layout.min_gap_m) == (0.8, 0.0)


def test_layout_describes_the_whole_plant_in_layout_order():
    config = default_layout()
    layout = layout_message(Engine(config))
    assert [(node.id, node.label) for node in layout.inputs] == [
        (node.id, node.label) for node in config.inputs]
    assert [(node.id, node.label) for node in layout.outputs] == [
        (node.id, node.label) for node in config.outputs]
    for sent, nodes in ((layout.merges, config.merges), (layout.sorters, config.sorters)):
        assert [(node.id, node.position.x_m, node.position.y_m) for node in sent] == [
            (node.id, node.position.x_m, node.position.y_m) for node in nodes]
    assert [belt.id for belt in layout.belts] == [belt.id for belt in config.belts]
    for sent, belt in zip(layout.belts, config.belts):
        assert (sent.source_id, sent.target_id) == (belt.source_id, belt.target_id)
        assert (sent.start.x_m, sent.start.y_m, sent.end.x_m, sent.end.y_m) == (
            belt.start.x_m, belt.start.y_m, belt.end.x_m, belt.end.y_m)
        assert (sent.length_m, sent.speed_m_s) == (belt.length_m, belt.speed_m_s)


def test_layout_does_not_include_input_rates():
    # Rates will change at run time: they belong in the snapshots, not here.
    layout = layout_message(Engine(default_layout())).model_dump()
    assert set(layout["inputs"][0]) == {"id", "label", "position"}


@pytest.mark.parametrize(("tick", "time_s"), [(1, 0.0), (0, 0.05), (20, 1.05)])
def test_tick_and_time_must_agree(tick, time_s):
    valid = layout_message(Engine()).model_dump()
    with pytest.raises(ValidationError, match="time_s must equal"):
        LayoutMessage(**{**valid, "tick": tick, "time_s": time_s})


def test_time_matches_the_engine_after_many_ticks():
    engine = run(Engine(), 12_345)
    snapshot = snapshot_message(engine, running=True)
    assert (snapshot.tick, snapshot.time_s) == (engine.tick, engine.time_s)


@pytest.mark.parametrize("field", ["time_s", "min_gap_m", "baggage_length_m"])
def test_nan_and_infinity_are_rejected(field):
    valid = layout_message(Engine()).model_dump()
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            LayoutMessage(**{**valid, field: value})


def test_unknown_fields_are_rejected():
    valid = layout_message(Engine()).model_dump()
    with pytest.raises(ValidationError):
        LayoutMessage(**valid, extra=1)


# Snapshots


def test_initial_snapshot_is_empty_with_missing_mean():
    snapshot = snapshot_message(Engine(), running=False)
    assert snapshot.type == "snapshot"
    assert (snapshot.tick, snapshot.time_s, snapshot.running) == (0, 0.0, False)
    assert snapshot.baggage == [] and snapshot.events == []
    assert snapshot.stats.mean_travel_time_s is None


def test_snapshot_bags_match_the_belt_in_order():
    engine = run(Engine(), 400)
    snapshot = snapshot_message(engine, running=True)
    assert [(b.id, b.conveyor_id, b.position_m, b.length_m, b.destination_id, b.entered_at_s)
            for b in snapshot.baggage] == [
        (b.id, b.conveyor_id, b.position_m, b.length_m, b.destination_id, b.entered_at_s)
        for b in engine.conveyors["belt-1"].baggage
    ]
    assert snapshot.baggage


def test_snapshot_stats_are_the_engine_stats():
    engine = run(Engine(), 600)
    stats = engine.stats()
    assert stats.throughput > 0  # a non-trivial value to compare
    sent = snapshot_message(engine, running=True).stats.model_dump()
    lists = {"belts", "inputs"}
    expected = {name: getattr(stats, name) for name in StatsState.model_fields if name not in lists}
    assert {name: value for name, value in sent.items() if name not in lists} == expected
    assert sent["inputs"] == [{"input_id": node.input_id, "waiting": node.waiting}
                              for node in stats.inputs]
    assert sent["belts"] == [
        {"belt_id": belt.belt_id, "bags": belt.bags, "capacity": belt.capacity,
         "occupancy": belt.occupancy}
        for belt in stats.belts
    ]


def test_snapshot_has_every_belt_with_its_stop_fault_and_occupancy_in_layout_order():
    engine = run(Engine(default_layout()), 1200)
    engine.stop_belt("line-2")
    engine.fault_belt("line-2")
    engine.fault_belt("branch-1")
    engine.conveyors["line-1"].congested = True
    snapshot = snapshot_message(engine, running=False)
    assert [(belt.id, belt.stopped, belt.faulty, belt.congested) for belt in snapshot.belts] == [
        (belt.id, belt.id == "line-2", belt.id in {"line-2", "branch-1"}, belt.id == "line-1")
        for belt in engine.layout.belts]
    line = next(belt for belt in snapshot.stats.belts if belt.belt_id == "line-1")
    assert (line.bags, line.capacity) == (len(engine.conveyors["line-1"].baggage), 7)
    assert line.occupancy == line.bags / 7


def test_snapshot_reports_wrong_sorting_settings_and_the_missorted_bag():
    engine = Engine(default_layout())
    snapshot = snapshot_message(engine, running=False)
    assert (snapshot.missort_probability, snapshot.missort_forced) == (0.0, False)
    engine.set_missort_probability(0.3)
    engine.force_missort()
    snapshot = snapshot_message(engine, running=False)
    assert (snapshot.missort_probability, snapshot.missort_forced) == (0.3, True)
    engine = run(engine, 600)
    sent = {bag.id: bag.missorted_to_id for bag in snapshot_message(engine, running=True).baggage}
    expected = {bag.id: bag.missorted_to_id for conveyor in engine.conveyors.values()
                for bag in conveyor.baggage}
    assert sent == expected
    assert any(sent.values()) and None in sent.values()


def test_snapshot_reports_when_each_bag_last_moved_and_its_prolonged_wait():
    engine = Engine(default_layout())
    engine = run(engine, 600)
    engine.fault_belt("line-1")
    engine = run(engine, 800)
    sent = {bag.id: (bag.moved_at_s, bag.prolonged_wait)
            for bag in snapshot_message(engine, running=True).baggage}
    expected = {bag.id: (bag.moved_at_s, bag.prolonged_wait)
                for conveyor in engine.conveyors.values() for bag in conveyor.baggage}
    assert sent == expected
    assert any(waiting for _, waiting in sent.values())
    assert not all(waiting for _, waiting in sent.values())


def test_snapshot_lists_open_alarms_then_the_latest_resolved_ones():
    engine = Engine(default_layout())
    assert snapshot_message(engine, running=False).alarms == []
    engine = run(engine, 20)
    engine.fault_belt("line-2")
    engine.fault_belt("branch-1")
    engine.step()
    engine.acknowledge_alarm(1)
    engine.repair_belt("branch-1")
    snapshot = snapshot_message(engine, running=False)
    assert [alarm.model_dump() for alarm in snapshot.alarms] == [
        {"id": 1, "kind": "belt_fault", "severity": "error", "state": "acknowledged",
         "message": "Belt fault: halted until repaired", "element_id": "line-2",
         "baggage_id": None, "raised_at_s": 1.0, "acknowledged_at_s": 1.05,
         "resolved_at_s": None},
        {"id": 2, "kind": "belt_fault", "severity": "error", "state": "resolved",
         "message": "Belt fault: halted until repaired", "element_id": "branch-1",
         "baggage_id": None, "raised_at_s": 1.0, "acknowledged_at_s": None,
         "resolved_at_s": 1.05},
    ]
    # The events say which alarm they concern.
    assert [(event.kind, event.alarm_id) for event in snapshot.events][-4:] == [
        ("belt_fault", 1), ("belt_fault", 2), ("alarm_acknowledged", 1), ("belt_repaired", 2)]


def test_snapshot_alarms_of_bags_name_the_bag_and_its_belt():
    engine = run(Engine(default_layout()), 600)
    engine.fault_belt("line-1")
    engine = run(engine, 800)
    sent = {alarm.baggage_id: alarm.element_id for alarm in snapshot_message(
        engine, running=True).alarms if alarm.kind == "prolonged_wait"}
    assert sent == {bag.id: bag.conveyor_id for conveyor in engine.conveyors.values()
                    for bag in conveyor.baggage if bag.prolonged_wait}
    assert sent


def test_snapshot_carries_only_new_events():
    engine = Engine()
    engine.events.record(1, 0.05, Severity.INFO, "first", "First")
    engine.events.record(2, 0.1, Severity.WARNING, "second", "Second", element_id="belt-1")
    assert [e.id for e in snapshot_message(engine, running=False).events] == [1, 2]
    [event] = snapshot_message(engine, running=False, after_event_id=1).events
    assert event.model_dump() == {
        "tick": 2, "time_s": 0.1, "id": 2, "severity": Severity.WARNING,
        "kind": "second", "message": "Second", "element_id": "belt-1", "baggage_id": None,
        "alarm_id": None,
    }
    assert snapshot_message(engine, running=False, after_event_id=2).events == []


def test_snapshot_round_trips_through_json():
    engine = run(Engine(minimal_layout(arrival_rate_bags_s=5.0)), 200)
    snapshot = snapshot_message(engine, running=True)
    assert snapshot.events  # the entrance queue has started
    data = json.loads(snapshot.model_dump_json())
    assert data["type"] == "snapshot"
    assert data["events"][0]["severity"] == "info"
    assert SnapshotMessage.model_validate(data) == snapshot


def test_error_message_has_its_type():
    assert ErrorMessage(message="bad").model_dump() == {"type": "error", "message": "bad"}


def test_snapshot_has_the_speed_and_every_input_rate():
    engine = Engine(default_layout())
    engine.set_arrival_rate("input-b2", 0.4)
    snapshot = snapshot_message(engine, running=True, speed=5)
    assert snapshot.speed == 5
    assert [(node.id, node.arrival_rate_bags_s) for node in snapshot.inputs] == [
        (node.id, 0.4 if node.id == "input-b2" else 0.15) for node in engine.layout.inputs]


def test_snapshot_has_the_run_number():
    assert snapshot_message(Engine(), running=False).run == 1
    assert snapshot_message(Engine(), running=False, run=3).run == 3
    with pytest.raises(ValidationError):
        SnapshotMessage.model_validate({**snapshot_message(Engine(), running=False).model_dump(), "run": 0})


def test_command_record_round_trips_through_json():
    record = CommandRecord(tick=40, time_s=2.0,
                           command=SetRateCommand(type="set_rate", input_id="input-a1", rate_bags_s=0.5))
    data = json.loads(record.model_dump_json())
    assert data == {"tick": 40, "time_s": 2.0,
                    "command": {"type": "set_rate", "input_id": "input-a1", "rate_bags_s": 0.5}}
    assert CommandRecord.model_validate(data) == record
    with pytest.raises(ValidationError):
        CommandRecord(tick=40, time_s=1.0, command=record.command)
