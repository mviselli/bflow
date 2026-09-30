"""Generation at every input of the plant, and transfers from belt to belt."""

from collections import Counter
from dataclasses import replace

import pytest

from bflow.core.engine import Engine
from bflow.core.layout import minimal_layout
from bflow.core.models import Baggage
from tests.layouts import compact_layout


def with_rates(*rates):
    layout = compact_layout()
    inputs = tuple(replace(node, arrival_rate_bags_s=rate)
                   for node, rate in zip(layout.inputs, rates, strict=True))
    return replace(layout, inputs=inputs)


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def all_bags(engine):
    on_belts = [bag for conveyor in engine.conveyors.values() for bag in conveyor.baggage]
    return on_belts + [bag for queue in engine.waiting.values() for bag in queue]


def test_each_input_generates_at_its_own_rate():
    engine = Engine(with_rates(0.1, 0.5, 2))
    advance(engine, 12000)
    assert engine.generated_by_input == {"input-a": 60, "input-b": 300, "input-c": 1200}
    assert engine.generated_count == 1560


def test_a_zero_rate_input_generates_nothing_and_leaves_the_others_running():
    engine = Engine(with_rates(0, 1, 1))
    advance(engine, 200)
    assert engine.generated_by_input == {"input-a": 0, "input-b": 10, "input-c": 10}
    assert not engine.conveyors["feeder-a-1"].baggage


def test_bags_are_numbered_in_input_order_within_a_tick():
    engine = Engine(with_rates(1, 1, 1))
    advance(engine, 20)
    assert [(input_id, conveyor.baggage[0].id)
            for input_id, conveyor in engine.input_conveyors.items()] == [
        ("input-a", "bag-1"), ("input-b", "bag-2"), ("input-c", "bag-3"),
    ]
    assert all(conveyor.baggage[0].generated_at_s == 1
               for conveyor in engine.input_conveyors.values())


def test_every_input_sends_bags_to_all_outputs_in_about_equal_shares():
    engine = Engine(with_rates(5, 5, 5))
    advance(engine, 4000)
    for input_id, queue in engine.waiting.items():
        shares = Counter(bag.destination_id for bag in queue)
        assert set(shares) == {"output-1", "output-2", "output-3"}, input_id
        for count in shares.values():
            assert 0.28 < count / len(queue) < 0.39, (input_id, shares)


def test_same_seed_draws_the_same_destinations():
    def destinations(seed):
        engine = Engine(compact_layout(), seed=seed)
        advance(engine, 2000)
        return sorted((bag.id, bag.destination_id) for bag in all_bags(engine))

    assert destinations(42) == destinations(42)
    assert destinations(42) != destinations(43)


def test_each_input_has_its_own_queue_and_queue_event():
    engine = Engine(with_rates(0.25, 10, 0.25))
    advance(engine, 20)
    assert engine.waiting_count == len(engine.waiting["input-b"]) > 0
    (event,) = engine.events.recent
    assert (event.kind, event.element_id) == ("entrance_queue_started", "input-b")


def place(engine, conveyor_id, name, position):
    bag = Baggage(name, "output-1", 0.6, 0, conveyor_id, position, entered_at_s=0)
    engine.conveyors[conveyor_id].baggage.append(bag)
    return bag


def test_a_bag_at_the_end_of_a_belt_starts_the_next_belt_without_moving_again():
    engine = Engine(with_rates(0, 0, 0))
    bag = place(engine, "feeder-a-1", "bag", 7.38)
    engine.step()
    assert engine.conveyors["feeder-a-1"].baggage == []
    assert engine.conveyors["feeder-a-2"].baggage == [bag]
    assert (bag.conveyor_id, bag.position_m) == ("feeder-a-2", 0)
    engine.step()
    assert bag.position_m == pytest.approx(0.05)


@pytest.mark.parametrize("offset, moved", [(-1e-9, False), (0, True)])
def test_a_transfer_needs_the_bag_length_plus_the_gap_on_the_next_belt(offset, moved):
    engine = Engine(with_rates(0, 0, 0))
    bag = place(engine, "feeder-a-1", "bag", 7.4)
    ahead = place(engine, "feeder-a-2", "ahead", 0)
    # Isolate the check from movement: only the positions after it count.
    engine._move()
    ahead.position_m = 0.6 + 0.2 + offset
    leaving = engine._evaluate_transfers()
    assert (engine.conveyors["feeder-a-1"] in leaving) == moved
    engine._apply_transfers(leaving)
    assert bag.conveyor_id == ("feeder-a-2" if moved else "feeder-a-1")


def test_the_full_plant_conserves_bags_and_spacing_every_tick():
    engine = Engine(compact_layout())
    gap = engine.layout.min_gap_m
    for _ in range(12000):
        engine.step()
        assert engine.stats().is_conserved
        ids = [bag.id for bag in all_bags(engine)]
        assert len(ids) == len(set(ids)) == engine.generated_count - engine.exited_count
        for conveyor in engine.conveyors.values():
            bags = conveyor.baggage
            for bag in bags:
                assert bag.conveyor_id == conveyor.config.id
                assert 0 <= bag.position_m <= conveyor.config.length_m - bag.length_m + 1e-12
            for rear, front in zip(bags, bags[1:]):
                assert rear.position_m + rear.length_m + gap <= front.position_m + 1e-12


def test_a_new_rate_counts_arrivals_from_the_change():
    # 0.5 bags/s: one arrival every 40 ticks, at ticks 40, 80, ... 960.
    engine = Engine(minimal_layout(arrival_rate_bags_s=0.5))
    for _ in range(1000):
        engine.step()
    assert engine.generated_count == 25
    engine.set_arrival_rate("input-a", 2)
    # 2 bags/s from tick 1000: the next arrival a full interval (10 ticks) later.
    arrivals = []
    for _ in range(40):
        engine.step()
        if engine.generated_count > 25 + len(arrivals):
            arrivals.append(engine.tick)
    assert arrivals == [1010, 1020, 1030, 1040]
    assert engine.arrival_rates == {"input-a": 2}


def test_a_zero_rate_stops_arrivals_and_keeps_the_waiting_bags():
    # 30 bags/s against about 10 admitted per second: a queue builds up.
    engine = Engine(minimal_layout(length_m=0.6, arrival_rate_bags_s=30))
    for _ in range(100):
        engine.step()
    waiting = engine.waiting_count
    assert waiting > 0
    engine.set_arrival_rate("input-a", 0)
    for _ in range(20):
        engine.step()
    assert engine.generated_count == 150
    assert 0 < engine.waiting_count < waiting


def test_a_rate_change_records_one_event_and_repeats_do_nothing():
    engine = Engine(minimal_layout(arrival_rate_bags_s=0.5))
    engine.set_arrival_rate("input-a", 0.5)
    assert list(engine.events.since(0)) == []
    engine.step()
    engine.set_arrival_rate("input-a", 0.25)
    engine.set_arrival_rate("input-a", 0.25)
    [event] = list(engine.events.since(0))
    assert (event.kind, event.element_id, event.tick) == ("input_rate_changed", "input-a", 1)


@pytest.mark.parametrize("input_id, rate", [("input-x", 1), ("input-a", -1),
                                            ("input-a", float("nan"))])
def test_an_invalid_rate_command_is_rejected(input_id, rate):
    engine = Engine(minimal_layout())
    with pytest.raises(ValueError):
        engine.set_arrival_rate(input_id, rate)
    assert engine.arrival_rates == {"input-a": 0.5}
