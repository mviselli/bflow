"""Wrong sorting: a sorter sends a bag down a wrong branch.

The probability is zero at first; the operator can set it or force the
error on the next bag. Each passage through a sorter is decided once, the
error is one error event at the sorter, and the arrival at the wrong output
is only classified there (a wrong exit), not counted as a second error.
"""

from dataclasses import replace

import pytest

from bflow.core.engine import Engine
from bflow.core.events import Severity
from bflow.core.layout import default_layout
from bflow.core.models import Baggage
from tests.layouts import compact_layout


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def quiet(layout):
    """The same plant with no arrivals, for bags placed by hand."""
    return Engine(replace(layout, inputs=tuple(replace(node, arrival_rate_bags_s=0)
                                               for node in layout.inputs)))


def place(engine, conveyor_id, name, destination_id, position):
    bag = Baggage(name, destination_id, engine.layout.baggage_length_m, 0, conveyor_id, position,
                  entered_at_s=0)
    engine.conveyors[conveyor_id].baggage.insert(0, bag)
    engine.admitted_count += 1  # keeps the counters consistent for stats()
    engine.generated_count += 1
    return bag


def at_end(engine, conveyor_id):
    return engine.conveyors[conveyor_id].config.length_m - engine.layout.baggage_length_m


def kinds(engine, *wanted):
    return [(event.severity, event.kind, event.element_id, event.baggage_id)
            for event in engine.events.recent if event.kind in wanted]


def test_at_zero_probability_no_random_draw_is_made_for_sorting():
    engine = Engine(default_layout())
    draws = []
    random = engine.rng.random
    engine.rng.random = lambda: draws.append(1) or random()
    advance(engine, 6000)
    assert draws == []
    assert (engine.missort_probability, engine.misdelivered_count) == (0.0, 0)


def test_a_forced_error_sends_the_next_bag_down_a_wrong_branch_once():
    engine = quiet(compact_layout())
    bag = place(engine, "collector", "bag", "output-2", at_end(engine, "collector") - 0.5)
    engine.force_missort()
    engine.force_missort()  # a repeat before the bag arrives changes nothing
    advance(engine, 9)
    assert bag.sorted_at_id is None and engine.missort_forced
    engine.step()  # the front edge reaches the end: the sorter decides
    assert bag.sorted_at_id == "sorter"
    assert bag.missorted_to_id in {"output-1", "output-3"}
    assert not engine.missort_forced
    advance(engine, 400)
    assert bag.exited_at_s is not None
    assert engine.misdelivered_by_output[bag.missorted_to_id] == 1
    assert kinds(engine, "missort_forced", "wrong_sorting", "wrong_exit") == [
        (Severity.INFO, "missort_forced", None, None),
        (Severity.ERROR, "wrong_sorting", "sorter", "bag"),
        (Severity.INFO, "wrong_exit", bag.missorted_to_id, "bag"),
    ]
    stats = engine.stats()
    # One error at the sorter; the wrong exit is classified, not counted again.
    assert (stats.errors, stats.misdelivered, stats.correctly_delivered) == (1, 1, 0)


def test_a_missorted_bag_held_on_a_faulty_branch_counts_each_problem_once():
    # A forced wrong sorting, then a fault on the wrong branch the bag goes
    # down: the bag waits there past 30 s, its alarms are acknowledged, the
    # branch is repaired and the bag exits at the wrong output.
    engine = quiet(compact_layout())
    bag = place(engine, "collector", "bag", "output-2", at_end(engine, "collector") - 0.5)
    engine.force_missort()
    while bag.missorted_to_id is None:
        engine.step()
    branch = engine.sorter_routes["sorter"][bag.missorted_to_id]
    engine.fault_belt(branch)
    advance(engine, 700)
    assert (bag.conveyor_id, bag.prolonged_wait) == (branch, True)
    for alarm_id in list(engine.alarms):
        engine.acknowledge_alarm(alarm_id)
    engine.repair_belt(branch)
    advance(engine, 400)
    assert bag.exited_at_s is not None
    assert kinds(engine, "missort_forced", "wrong_sorting", "belt_fault", "prolonged_wait_started",
                 "alarm_acknowledged", "belt_repaired", "prolonged_wait_resolved", "wrong_exit") == [
        (Severity.INFO, "missort_forced", None, None),
        (Severity.ERROR, "wrong_sorting", "sorter", "bag"),
        (Severity.ERROR, "belt_fault", branch, None),
        (Severity.WARNING, "prolonged_wait_started", branch, "bag"),
        (Severity.INFO, "alarm_acknowledged", branch, None),
        (Severity.INFO, "alarm_acknowledged", branch, "bag"),
        (Severity.INFO, "belt_repaired", branch, None),
        (Severity.INFO, "prolonged_wait_resolved", branch, "bag"),
        (Severity.INFO, "wrong_exit", bag.missorted_to_id, "bag"),
    ]
    stats = engine.stats()
    # Two errors (the sorting, the fault), one warning (the wait), one wrong
    # exit; acknowledging, repairing and exiting count nothing more.
    assert (stats.errors, stats.wrong_sortings, stats.faults) == (2, 1, 1)
    assert (stats.warnings, stats.prolonged_waits) == (1, 1)
    assert (stats.misdelivered, stats.correctly_delivered) == (1, 0)
    assert (stats.active_errors, stats.active_warnings) == (0, 0)
    assert stats.is_conserved


def test_a_forced_error_takes_only_one_bag():
    engine = quiet(compact_layout())
    first = place(engine, "collector", "first", "output-1", 4.0)
    second = place(engine, "collector", "second", "output-3", 2.0)
    engine.force_missort()
    advance(engine, 800)
    assert first.missorted_to_id is not None
    assert second.missorted_to_id is None
    assert (engine.misdelivered_count, engine.correctly_delivered_count) == (1, 1)


def test_a_bag_waiting_at_a_sorter_is_decided_only_once():
    engine = quiet(compact_layout())
    engine.set_missort_probability(1e-9)  # a draw is made, an error almost never
    draws = []
    random = engine.rng.random
    engine.rng.random = lambda: draws.append(engine.tick) or random()
    engine.stop_belt("branch-2")
    place(engine, "branch-2", "blocker", "output-2", 0.0)
    bag = place(engine, "collector", "bag", "output-2", at_end(engine, "collector"))
    advance(engine, 200)
    # The bag waits at the sorter for 10 s, but the sorter drew only once.
    assert bag.conveyor_id == "collector"
    assert draws == [1]
    assert bag.missorted_to_id is None


def test_a_missorted_bag_passes_the_next_sorters_without_a_new_decision():
    engine = quiet(default_layout())
    engine.set_missort_probability(1)
    bag = place(engine, "line-1", "bag", "output-1", at_end(engine, "line-1"))
    engine.step()
    # The only wrong branch at divert-1 is the line onwards, towards 2, 3 or 4.
    assert bag.missorted_to_id in {"output-2", "output-3", "output-4"}
    wrong = bag.missorted_to_id
    advance(engine, 600)
    assert bag.exited_at_s is not None and bag.missorted_to_id == wrong
    assert engine.misdelivered_by_output[wrong] == 1
    assert [kind for _, kind, _, _ in kinds(engine, "wrong_sorting")] == ["wrong_sorting"]


def test_at_probability_one_every_bag_exits_at_a_wrong_output_with_one_error_each():
    engine = Engine(compact_layout())
    engine.set_missort_probability(1)
    advance(engine, 6000)
    stats = engine.stats()
    assert stats.correctly_delivered == 0
    assert stats.misdelivered > 50
    sorted_bags = [bag for conveyor in engine.conveyors.values() for bag in conveyor.baggage
                   if bag.missorted_to_id is not None]
    assert stats.errors == stats.misdelivered + len(sorted_bags)
    assert stats.is_conserved


def test_the_error_rate_follows_the_probability():
    engine = Engine(compact_layout(), seed=3)
    engine.set_missort_probability(0.1)
    advance(engine, 24000)
    stats = engine.stats()
    sorted_count = stats.exited + sum(1 for conveyor in engine.conveyors.values()
                                      for bag in conveyor.baggage if bag.sorted_at_id)
    assert 0.06 < stats.errors / sorted_count < 0.14
    assert stats.misdelivered <= stats.errors
    assert stats.is_conserved


def test_setting_the_probability_records_a_change_and_rejects_bad_values():
    engine = Engine(compact_layout())
    engine.set_missort_probability(0.25)
    engine.set_missort_probability(0.25)
    engine.set_missort_probability(0)
    assert [event.message for event in engine.events.recent] == [
        "Wrong sorting probability set to 0.25", "Wrong sorting probability set to 0"]
    for bad in (-0.1, 1.5, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="probability"):
            engine.set_missort_probability(bad)
    assert engine.stats().errors == 0


def test_a_bag_cannot_be_missorted_to_its_own_destination():
    with pytest.raises(ValueError, match="another output"):
        Baggage("bag", "output-1", 0.6, 0, "line-1", 0, entered_at_s=0,
                missorted_to_id="output-1")


def test_the_same_errors_at_the_same_ticks_give_the_same_run():
    def run():
        engine = Engine(default_layout(), seed=9)
        for tick in range(4000):
            if tick == 100:
                engine.set_missort_probability(0.3)
            if tick == 2000:
                engine.force_missort()
            engine.step()
        bags = [(bag.id, bag.conveyor_id, bag.position_m, bag.missorted_to_id)
                for conveyor in engine.conveyors.values() for bag in conveyor.baggage]
        return engine.stats(), bags, [event.kind for event in engine.events.recent]

    assert run() == run()
