"""Counts and times: entrance waiting excluded, wrong exits included."""

import pytest

from bflow.core.engine import Engine
from bflow.core.models import Baggage, ConveyorConfig, SimulationConfig


def test_no_completed_journey_has_no_mean_even_with_waiting_and_transit():
    engine = Engine(SimulationConfig(arrival_rate_bags_s=60))
    assert engine.mean_travel_time_s is None
    assert engine.in_transit_count == engine.exited_count == 0
    engine.step()
    assert len(engine.waiting) == 2
    assert engine.in_transit_count == 1
    assert engine.correctly_delivered_count == engine.misdelivered_count == 0
    assert engine.mean_travel_time_s is None


def test_known_journey_times_exclude_waiting_and_include_wrong_exit():
    engine = Engine(SimulationConfig(arrival_rate_bags_s=0))
    for _ in range(100):
        engine.step()
    # Two bags with different admission times, both at the end of the belt.
    correct = Baggage('first', engine.config.output_id, 0.6, 0,
                      engine.config.conveyor.id, 9.4, entered_at_s=2)
    engine.conveyor.baggage.append(correct)
    engine.step()
    assert engine.mean_travel_time_s == pytest.approx(3.05)
    wrong = Baggage('second', 'another-output', 0.6, 0,
                    engine.config.conveyor.id, 9.4, entered_at_s=4)
    engine.conveyor.baggage.append(wrong)
    engine.step()
    assert engine.correctly_delivered_count == 1
    assert engine.misdelivered_count == 1
    assert engine.exited_count == 2
    assert engine.in_transit_count == 0
    assert engine.mean_travel_time_s == pytest.approx((3.05 + 1.10) / 2)
    assert correct.destination_id == engine.config.output_id
    assert wrong.destination_id == 'another-output'
    engine.step()
    assert engine.exited_this_tick == ()
    assert engine.exited_count == 2
    assert engine.mean_travel_time_s == pytest.approx(2.075)


def test_actual_queue_wait_does_not_enter_mean_and_counts_conserve_each_tick():
    engine = Engine(SimulationConfig(
        conveyor=ConveyorConfig(length_m=2), arrival_rate_bags_s=10,
    ))
    durations = []
    waited = False
    for _ in range(12000):
        engine.step()
        for bag in engine.exited_this_tick:
            waited |= bag.entered_at_s > bag.generated_at_s
            durations.append(bag.exited_at_s - bag.entered_at_s)
        assert engine.admitted_count == (
            engine.correctly_delivered_count + engine.misdelivered_count + engine.in_transit_count
        )
        assert engine.generated_count == engine.admitted_count + len(engine.waiting)
        if durations:
            assert engine.mean_travel_time_s == pytest.approx(sum(durations) / len(durations))
        else:
            assert engine.mean_travel_time_s is None
    assert waited
    assert engine.correctly_delivered_count == len(durations) > 0
    assert engine.misdelivered_count == 0


def test_counts_and_mean_are_independent_between_runs():
    config = SimulationConfig(conveyor=ConveyorConfig(length_m=0.6), arrival_rate_bags_s=20)
    first, second = Engine(config), Engine(config)
    first.step()
    first.step()
    assert first.exited_count == 1
    assert first.mean_travel_time_s == pytest.approx(0.05)
    assert second.exited_count == second.in_transit_count == 0
    assert second.mean_travel_time_s is None
