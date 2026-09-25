"""Statistics snapshot: a consistent picture of the engine counters."""

import dataclasses

import pytest

from bflow.core.engine import Engine
from bflow.core.models import ConveyorConfig, SimulationConfig


def test_initial_snapshot_is_empty_and_conserved():
    stats = Engine().stats()
    assert (stats.tick, stats.time_s) == (0, 0)
    assert stats.generated == stats.waiting == stats.admitted == stats.exited == 0
    assert stats.mean_travel_time_s is None
    assert stats.is_conserved


def test_snapshot_matches_engine_and_does_not_follow_later_steps():
    engine = Engine(SimulationConfig(conveyor=ConveyorConfig(length_m=2), arrival_rate_bags_s=10))
    for _ in range(1000):
        engine.step()
    stats = engine.stats()
    assert stats.tick == engine.tick == 1000
    assert stats.time_s == engine.time_s == 50
    assert stats.generated == engine.generated_count
    assert stats.waiting == len(engine.waiting) > 0
    assert stats.admitted == engine.admitted_count
    assert stats.correctly_delivered == engine.correctly_delivered_count > 0
    assert stats.misdelivered == engine.misdelivered_count == 0
    assert stats.in_transit == engine.in_transit_count
    assert stats.exited == engine.exited_count
    assert stats.mean_travel_time_s == engine.mean_travel_time_s
    assert stats.is_conserved
    engine.step()
    assert stats.tick == 1000
    with pytest.raises(dataclasses.FrozenInstanceError):
        stats.tick = 0


def test_conservation_check_detects_lost_or_duplicated_baggage():
    stats = Engine().stats()
    assert not dataclasses.replace(stats, in_transit=1).is_conserved
    assert not dataclasses.replace(stats, generated=1).is_conserved


def test_every_snapshot_of_a_long_run_is_conserved():
    engine = Engine(SimulationConfig(conveyor=ConveyorConfig(length_m=3), arrival_rate_bags_s=2))
    for _ in range(12000):
        engine.step()
        assert engine.stats().is_conserved


def test_same_seed_and_steps_reproduce_stats_and_events():
    config = SimulationConfig(conveyor=ConveyorConfig(length_m=2), arrival_rate_bags_s=3)
    runs = []
    for _ in range(2):
        engine = Engine(config, seed=11)
        snapshots = []
        for _ in range(12000):
            engine.step()
            snapshots.append(engine.stats())
        runs.append((snapshots, engine.events.since(0), engine.events.counts))
    assert runs[0] == runs[1]
    assert runs[0][1]
