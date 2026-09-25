"""Regular arrivals, FIFO waiting and the physical space required for admission."""

import pytest

from bflow.core.engine import Engine
from bflow.core.models import ConveyorConfig, SimulationConfig


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def test_first_arrival_waits_for_a_full_interval():
    engine = Engine(SimulationConfig(arrival_rate_bags_s=2))
    advance(engine, 9)
    assert engine.generated_count == engine.admitted_count == 0
    engine.step()
    bag = engine.conveyor.baggage[0]
    assert engine.generated_count == engine.admitted_count == 1
    assert bag.generated_at_s == bag.entered_at_s == 0.5
    assert bag.destination_id == engine.config.output_id
    assert bag.conveyor_id == engine.config.conveyor.id
    assert bag.position_m == 0
    assert not engine.waiting


def test_blocked_entrance_preserves_all_demand_and_identifiers(monkeypatch):
    engine = Engine(SimulationConfig(
        conveyor=ConveyorConfig(length_m=0.6), arrival_rate_bags_s=10,
    ))
    monkeypatch.setattr(engine, "_evaluate_transfers", lambda: ())
    for _ in range(200):
        engine.step()
        assert engine.generated_count == engine.admitted_count + len(engine.waiting)
        assert engine.admitted_count == engine.exited_count + len(engine.conveyor.baggage)
    assert engine.generated_count == 100
    assert engine.admitted_count == 1
    assert [bag.id for bag in engine.waiting] == [f"bag-{i}" for i in range(2, 101)]
    assert all(bag.entered_at_s is None and bag.conveyor_id is None for bag in engine.waiting)
    assert all(bag.position_m == 0 and bag.exited_at_s is None for bag in engine.waiting)


@pytest.mark.parametrize("rate, expected", [(0, 0), (0.3, 180), (3, 1800), (50, 30000)])
def test_rate_over_ten_minutes_including_multiple_arrivals_per_tick(rate, expected):
    engine = Engine(SimulationConfig(arrival_rate_bags_s=rate))
    advance(engine, 12000)
    assert engine.generated_count == expected
    assert engine.generated_count == engine.admitted_count + len(engine.waiting)


def test_multiple_arrivals_in_same_tick_keep_generation_time():
    engine = Engine(SimulationConfig(arrival_rate_bags_s=60))
    engine.step()
    assert engine.generated_count == 3
    assert engine.admitted_count == 1
    assert [bag.id for bag in engine.waiting] == ["bag-2", "bag-3"]
    assert all(bag.generated_at_s == 0.05 for bag in engine.waiting)


@pytest.mark.parametrize("offset, admitted", [(-1e-9, False), (0, True), (1e-9, True)])
def test_admission_requires_baggage_length_plus_free_gap(offset, admitted):
    engine = Engine(SimulationConfig(arrival_rate_bags_s=20))
    engine.step()
    first = engine.conveyor.baggage[0]
    # Isolate admission at an exact boundary, independently of movement.
    engine.step()
    first.position_m = engine.config.baggage_length_m + engine.config.min_gap_m + offset
    engine._admit()
    assert engine.admitted_count == (2 if admitted else 1)
    assert len(engine.waiting) == (0 if admitted else 1)
    if admitted:
        second, original = engine.conveyor.baggage
        assert original is first
        assert second.position_m == 0
        assert original.position_m >= second.length_m + engine.config.min_gap_m


def test_released_entrance_admits_oldest_without_resetting_generation_time():
    engine = Engine(SimulationConfig(arrival_rate_bags_s=20))
    advance(engine, 4)
    oldest = engine.waiting[0]
    assert oldest.id == "bag-2"
    engine.conveyor.baggage[0].position_m = 2
    engine.step()
    assert engine.conveyor.baggage[0] is oldest
    assert oldest.generated_at_s == 0.1
    assert oldest.entered_at_s == 0.25
    assert [bag.id for bag in engine.waiting] == ["bag-3", "bag-4", "bag-5"]


def test_exact_length_baggage_can_enter_empty_belt_without_end_gap():
    engine = Engine(SimulationConfig(
        conveyor=ConveyorConfig(length_m=0.6), baggage_length_m=0.6,
        arrival_rate_bags_s=20,
    ))
    engine.step()
    assert engine.admitted_count == 1
    assert not engine.waiting
    assert engine.conveyor.baggage[0].position_m == 0


def test_same_seed_and_config_reproduce_bags_queue_and_counts():
    config = SimulationConfig(arrival_rate_bags_s=7)
    first, second = Engine(config, seed=42), Engine(config, seed=42)
    advance(first, 200)
    advance(second, 200)
    assert first.conveyor == second.conveyor
    assert first.waiting == second.waiting
    assert first.generated_count == second.generated_count == 70
    assert first.admitted_count == second.admitted_count
    assert first.admitted_count > 1
