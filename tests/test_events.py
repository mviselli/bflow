"""Registro eventi: identificativi progressivi, cronologia limitata, condizioni."""

import pytest

from bflow.core.engine import Engine
from bflow.core.events import EventLog, Severity
from bflow.core.models import Baggage, ConveyorConfig, SimulationConfig


def test_ids_are_progressive_and_counts_survive_the_bounded_history():
    log = EventLog(max_recent=3)
    assert log.last_id == log.total_count == 0
    for tick in range(1, 6):
        log.record(tick, tick / 20, Severity.WARNING, "test", "prova")
    log.record(6, 0.3, "error", "test", "prova", element_id="belt-1", baggage_id="bag-1")
    assert [event.id for event in log.recent] == [4, 5, 6]
    assert log.total_count == log.last_id == 6
    assert log.counts == {Severity.INFO: 0, Severity.WARNING: 5, Severity.ERROR: 1}
    assert log.recent[-1].severity is Severity.ERROR
    assert log.recent[-1].element_id == "belt-1"
    assert log.recent[-1].baggage_id == "bag-1"


def test_since_returns_only_newer_retained_events():
    log = EventLog(max_recent=3)
    for tick in range(1, 6):
        log.record(tick, tick / 20, Severity.INFO, "test", "prova")
    assert [event.id for event in log.since(0)] == [3, 4, 5]
    assert [event.id for event in log.since(4)] == [5]
    assert log.since(5) == ()


@pytest.mark.parametrize("max_recent", [0, -1, 1.5, True])
def test_history_size_must_be_a_positive_integer(max_recent):
    with pytest.raises(ValueError):
        EventLog(max_recent=max_recent)


def test_unknown_severity_is_rejected():
    with pytest.raises(ValueError):
        EventLog().record(1, 0.05, "fatal", "test", "prova")


def test_normal_flow_produces_no_events():
    engine = Engine()
    for _ in range(12000):
        engine.step()
    assert engine.events.total_count == 0
    assert engine.stats().errors == engine.stats().warnings == 0


def test_blocked_entrance_records_the_queue_once(monkeypatch):
    engine = Engine(SimulationConfig(
        conveyor=ConveyorConfig(length_m=0.6), arrival_rate_bags_s=10,
    ))
    monkeypatch.setattr(engine, "_evaluate_transfers", lambda: ())
    for _ in range(200):
        engine.step()
    assert len(engine.waiting) == 99
    (event,) = engine.events.recent
    assert event.kind == "entrance_queue_started"
    assert event.severity is Severity.INFO
    assert event.element_id == engine.config.input_id
    assert (event.id, event.tick, event.time_s) == (1, 4, 0.2)


def test_queue_start_and_clear_are_recorded_at_the_changing_ticks():
    engine = Engine(SimulationConfig(arrival_rate_bags_s=0))
    for i in range(3):
        engine.waiting.append(Baggage(f"bag-{i}", engine.config.output_id, 0.6, 0))
    engine.generated_count = 3
    ticks_with_queue = []
    for _ in range(100):
        engine.step()
        if engine.waiting:
            ticks_with_queue.append(engine.tick)
    started, cleared = engine.events.recent
    assert (started.kind, cleared.kind) == ("entrance_queue_started", "entrance_queue_cleared")
    assert started.tick == ticks_with_queue[0] == 1
    assert cleared.tick == ticks_with_queue[-1] + 1
    assert engine.events.total_count == 2
    assert engine.admitted_count == 3


def test_events_are_independent_between_runs(monkeypatch):
    config = SimulationConfig(conveyor=ConveyorConfig(length_m=0.6), arrival_rate_bags_s=10)
    first, second = Engine(config), Engine(config)
    monkeypatch.setattr(first, "_evaluate_transfers", lambda: ())
    for _ in range(10):
        first.step()
    assert first.events.total_count == 1
    assert second.events.total_count == 0
