"""Statistics snapshot: a consistent picture of the engine counters."""

import dataclasses

import pytest

from bflow.core.engine import Engine
from bflow.core.layout import minimal_layout
from bflow.core.models import Baggage


def test_initial_snapshot_is_empty_and_conserved():
    stats = Engine().stats()
    assert (stats.tick, stats.time_s) == (0, 0)
    assert stats.generated == stats.waiting == stats.admitted == stats.exited == 0
    assert stats.mean_travel_time_s is None
    assert stats.is_conserved


def test_snapshot_matches_engine_and_does_not_follow_later_steps():
    engine = Engine(minimal_layout(length_m=2, arrival_rate_bags_s=10))
    for _ in range(1000):
        engine.step()
    stats = engine.stats()
    assert stats.tick == engine.tick == 1000
    assert stats.time_s == engine.time_s == 50
    assert stats.generated == engine.generated_count
    assert stats.waiting == engine.waiting_count > 0
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
    engine = Engine(minimal_layout(length_m=3, arrival_rate_bags_s=2))
    for _ in range(12000):
        engine.step()
        assert engine.stats().is_conserved


def test_same_seed_and_steps_reproduce_stats_and_events():
    layout = minimal_layout(length_m=2, arrival_rate_bags_s=3)
    runs = []
    for _ in range(2):
        engine = Engine(layout, seed=11)
        snapshots = []
        for _ in range(12000):
            engine.step()
            snapshots.append(engine.stats())
        runs.append((snapshots, engine.events.since(0), engine.events.counts))
    assert runs[0] == runs[1]
    assert runs[0][1]


def test_conservation_check_detects_per_input_belt_or_output_counts_that_do_not_add_up():
    engine = Engine(minimal_layout(length_m=2, arrival_rate_bags_s=10))
    for _ in range(100):
        engine.step()
    stats = engine.stats()
    assert stats.is_conserved and stats.waiting > 0 and stats.in_transit > 0
    (belt,) = stats.belts
    (node,) = stats.inputs
    assert not dataclasses.replace(
        stats, belts=(dataclasses.replace(belt, bags=belt.bags + 1),)).is_conserved
    assert not dataclasses.replace(
        stats, inputs=(dataclasses.replace(node, waiting=node.waiting - 1),)).is_conserved
    (output,) = stats.outputs
    assert stats.correctly_delivered > 0
    assert not dataclasses.replace(stats, outputs=(
        dataclasses.replace(output, correctly_delivered=output.correctly_delivered - 1),
    )).is_conserved
    assert not dataclasses.replace(stats, outputs=(
        dataclasses.replace(output, misdelivered=1),)).is_conserved


def test_occurrences_since_the_start_stay_while_active_alarms_go_back_down():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    engine.stop_belt("belt-1")
    for n in range(10):
        engine.conveyors["belt-1"].baggage.insert(0, Baggage(
            f"bag-{n}", "output-1", 0.6, 0, "belt-1", n * 0.9, entered_at_s=0))
    engine.fault_belt("belt-1")
    engine.set_missort_probability(0)
    for _ in range(600):
        engine.step()
    stats = engine.stats()
    # One fault, one congestion (10 of 12 bags) and ten bags still for 30 s.
    assert (stats.errors, stats.faults, stats.wrong_sortings) == (1, 1, 0)
    assert (stats.warnings, stats.congestions, stats.prolonged_waits) == (11, 1, 10)
    assert (stats.active_errors, stats.active_warnings) == (1, 11)
    # Acknowledging changes neither count.
    engine.acknowledge_alarm(1)
    assert engine.stats().active_errors == 1
    engine.repair_belt("belt-1")
    engine.restart_belt("belt-1")
    for _ in range(400):
        engine.step()
    stats = engine.stats()
    assert (stats.errors, stats.warnings) == (1, 11)
    assert (stats.active_errors, stats.active_warnings) == (0, 0)
