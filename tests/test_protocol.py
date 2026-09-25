"""Browser messages: strict command validation, snapshots faithful to the engine."""

import json

import pytest
from pydantic import ValidationError

from bflow.core.engine import STEP_MS, Engine
from bflow.core.events import Severity
from bflow.core.models import ConveyorConfig, SimulationConfig
from bflow.server.protocol import (
    ErrorMessage,
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
])
def test_invalid_commands_are_rejected(raw):
    with pytest.raises(ValidationError):
        parse_command(raw)


def test_commands_are_immutable():
    command = parse_command('{"type": "start"}')
    with pytest.raises(ValidationError):
        command.type = "pause"


# Tick and simulated time


def test_initial_layout_describes_the_default_route():
    layout = layout_message(Engine())
    assert layout.model_dump() == {
        "type": "layout",
        "tick": 0,
        "time_s": 0.0,
        "step_ms": STEP_MS,
        "input_id": "input-a",
        "output_id": "output-1",
        "conveyors": [{"id": "belt-1", "length_m": 10.0, "speed_m_s": 1.0}],
        "baggage_length_m": 0.6,
        "min_gap_m": 0.2,
    }


def test_layout_follows_a_custom_configuration():
    config = SimulationConfig(conveyor=ConveyorConfig(id="belt-x", length_m=4.0, speed_m_s=0.5),
                              baggage_length_m=0.8, min_gap_m=0.0)
    layout = layout_message(run(Engine(config), 3))
    assert (layout.tick, layout.time_s) == (3, 0.15)
    assert layout.conveyors[0].model_dump() == {"id": "belt-x", "length_m": 4.0, "speed_m_s": 0.5}
    assert (layout.baggage_length_m, layout.min_gap_m) == (0.8, 0.0)


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
    assert [(b.id, b.conveyor_id, b.position_m, b.length_m, b.destination_id)
            for b in snapshot.baggage] == [
        (b.id, b.conveyor_id, b.position_m, b.length_m, b.destination_id)
        for b in engine.conveyor.baggage
    ]
    assert snapshot.baggage


def test_snapshot_stats_are_the_engine_stats():
    engine = run(Engine(), 600)
    stats = engine.stats()
    expected = {name: getattr(stats, name) for name in StatsState.model_fields}
    assert snapshot_message(engine, running=True).stats.model_dump() == expected


def test_snapshot_carries_only_new_events():
    engine = Engine()
    engine.events.record(1, 0.05, Severity.INFO, "first", "First")
    engine.events.record(2, 0.1, Severity.WARNING, "second", "Second", element_id="belt-1")
    assert [e.id for e in snapshot_message(engine, running=False).events] == [1, 2]
    [event] = snapshot_message(engine, running=False, after_event_id=1).events
    assert event.model_dump() == {
        "tick": 2, "time_s": 0.1, "id": 2, "severity": Severity.WARNING,
        "kind": "second", "message": "Second", "element_id": "belt-1", "baggage_id": None,
    }
    assert snapshot_message(engine, running=False, after_event_id=2).events == []


def test_snapshot_round_trips_through_json():
    engine = run(Engine(SimulationConfig(arrival_rate_bags_s=5.0)), 200)
    snapshot = snapshot_message(engine, running=True)
    assert snapshot.events  # the entrance queue has started
    data = json.loads(snapshot.model_dump_json())
    assert data["type"] == "snapshot"
    assert data["events"][0]["severity"] == "info"
    assert SnapshotMessage.model_validate(data) == snapshot


def test_error_message_has_its_type():
    assert ErrorMessage(message="bad").model_dump() == {"type": "error", "message": "bad"}
