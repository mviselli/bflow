"""Transfers to the output of the minimal route."""

from copy import deepcopy

import pytest

from bflow.core.engine import Engine
from bflow.core.models import Baggage, ConveyorConfig, SimulationConfig


def make_engine(length=1, speed=1, rate=0):
    return Engine(SimulationConfig(
        conveyor=ConveyorConfig(length_m=length, speed_m_s=speed),
        arrival_rate_bags_s=rate,
    ))


def place(engine, name, position):
    bag = Baggage(name, engine.config.output_id, 0.6, 0,
                  engine.config.conveyor.id, position, entered_at_s=0)
    engine.conveyor.baggage.append(bag)
    return bag


@pytest.mark.parametrize('offset, ready', [(-1e-10, False), (0, True)])
def test_evaluation_is_read_only_and_does_not_exit_early(offset, ready):
    engine = make_engine()
    bag = place(engine, 'bag-1', 0.4 + offset)
    before = deepcopy(engine.conveyor)
    selected = engine._evaluate_transfers()
    assert bool(selected) == ready
    assert engine.conveyor == before
    assert bag.exited_at_s is None
    assert engine.exited_count == 0
    assert engine.exited_this_tick == ()
    assert engine._evaluate_transfers() == selected


def test_exit_sets_timestamp_and_is_not_repeated():
    engine = make_engine()
    bag = place(engine, 'bag-1', 0.38)
    engine.step()
    assert engine.exited_this_tick == (bag,)
    assert engine.conveyor.baggage == []
    assert bag.position_m == 0.4
    assert bag.conveyor_id is None
    assert bag.exited_at_s == 0.05
    assert bag.entered_at_s == 0
    assert bag.destination_id == engine.config.output_id
    engine.step()
    assert engine.exited_this_tick == ()
    assert engine.exited_count == 1
    assert bag.exited_at_s == 0.05


def test_departure_does_not_trigger_second_movement_of_follower():
    engine = make_engine(length=2, speed=100)
    rear = place(engine, 'bag-2', 0)
    front = place(engine, 'bag-1', 1)
    engine.step()
    assert engine.exited_this_tick == (front,)
    assert rear.position_m == pytest.approx(0.6)
    assert engine.conveyor.baggage == [rear]
    engine.step()
    assert engine.exited_this_tick == (rear,)
    assert rear.position_m == pytest.approx(1.4)


def test_exact_fit_new_admission_waits_until_next_tick_to_exit():
    engine = make_engine(length=0.6, rate=20)
    engine.step()
    first = engine.conveyor.baggage[0]
    assert engine.exited_count == 0
    engine.step()
    assert engine.exited_this_tick == (first,)
    second = engine.conveyor.baggage[0]
    assert second.id == 'bag-2'
    assert second.position_m == 0
    assert second.exited_at_s is None
    assert engine.exited_count == 1


def test_long_run_has_no_loss_duplicates_or_reordering():
    engine = make_engine(length=2, rate=10)
    seen = []
    for _ in range(12000):
        engine.step()
        seen.extend(bag.id for bag in engine.exited_this_tick)
        assert engine.admitted_count == engine.exited_count + len(engine.conveyor.baggage)
        assert engine.generated_count == engine.admitted_count + len(engine.waiting)
        assert engine.exited_count == len(seen)
    assert len(seen) > 0
    assert seen == [f'bag-{i}' for i in range(1, len(seen) + 1)]


def test_grouped_execution_reproduces_departures_and_state():
    first, second = make_engine(rate=5), make_engine(rate=5)
    first_exits, second_exits = [], []
    for _ in range(200):
        first.step()
        first_exits.extend(deepcopy(first.exited_this_tick))
    for _ in range(40):
        for _ in range(5):
            second.step()
            second_exits.extend(deepcopy(second.exited_this_tick))
    assert first_exits == second_exits
    assert first.exited_count == second.exited_count > 0
    assert first.conveyor == second.conveyor
    assert first.waiting == second.waiting
