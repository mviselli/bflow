"""Movimento, ingombri diversi e accumulo senza trasferimenti."""

import pytest

from bflow.core.engine import Engine
from bflow.core.models import Baggage, ConveyorConfig, SimulationConfig


def make_engine(speed=1, gap=0.2, length=10):
    return Engine(SimulationConfig(
        conveyor=ConveyorConfig(length_m=length, speed_m_s=speed),
        arrival_rate_bags_s=0, min_gap_m=gap,
    ))


def place(engine, identifier, position, length=0.6):
    bag = Baggage(identifier, engine.config.output_id, length, 0,
                  engine.conveyor.config.id, position, entered_at_s=0)
    engine.conveyor.baggage.append(bag)
    return bag


@pytest.mark.parametrize('speed', [0.1, 1, 3])
def test_free_baggage_moves_by_speed_times_simulated_time(speed):
    engine = make_engine(speed=speed)
    bag = place(engine, 'bag', 1)
    for _ in range(20):
        engine.step()
    assert bag.position_m == pytest.approx(1 + speed)
    assert bag.entered_at_s == 0


def test_newly_admitted_baggage_moves_only_on_next_tick():
    engine = Engine(SimulationConfig(arrival_rate_bags_s=20))
    engine.step()
    bag = engine.conveyor.baggage[0]
    assert bag.position_m == 0
    engine.step()
    assert bag.position_m == pytest.approx(0.05)


def test_large_step_stops_at_end_and_propagates_queue_with_mixed_lengths():
    engine = make_engine(speed=1000)
    rear = place(engine, 'rear', 0, 1.2)
    middle = place(engine, 'middle', 2, 0.4)
    front = place(engine, 'front', 8, 0.9)
    engine._move()
    assert front.position_m == pytest.approx(9.1)
    assert middle.position_m == pytest.approx(8.5)
    assert rear.position_m == pytest.approx(7.1)
    positions = [b.position_m for b in engine.conveyor.baggage]
    engine._move()
    assert [b.position_m for b in engine.conveyor.baggage] == positions
    assert [b.id for b in engine.conveyor.baggage] == ['rear', 'middle', 'front']


def test_tightly_spaced_bags_use_space_freed_in_same_tick():
    engine = make_engine()
    rear = place(engine, 'rear', 0)
    front = place(engine, 'front', 0.8)
    engine.step()
    assert rear.position_m == pytest.approx(0.05)
    assert front.position_m == pytest.approx(0.85)


@pytest.mark.parametrize('gap', [0, 0.2, 0.7])
def test_long_run_preserves_bounds_order_spacing_and_counts_every_tick(gap):
    engine = Engine(SimulationConfig(arrival_rate_bags_s=20, min_gap_m=gap))
    previous = {}
    for _ in range(2000):
        engine.step()
        bags = engine.conveyor.baggage
        assert engine.generated_count == engine.admitted_count + len(engine.waiting)
        assert engine.admitted_count == engine.exited_count + len(bags)
        assert len({b.id for b in bags}) == len(bags)
        for bag in bags:
            assert 0 <= bag.position_m <= 10 - bag.length_m + 1e-12
            if bag.id in previous:
                delta = bag.position_m - previous[bag.id]
                assert 0 <= delta <= 0.05 + 1e-12
        for rear, front in zip(bags, bags[1:]):
            assert rear.position_m + rear.length_m + gap <= front.position_m + 1e-12
            assert int(rear.id.split('-')[1]) > int(front.id.split('-')[1])
        previous = {b.id: b.position_m for b in bags}
    assert len(engine.waiting) > 0
    assert engine.exited_count > 0


def test_empty_belt_can_step():
    engine = make_engine()
    engine.step()
    assert engine.conveyor.baggage == []
