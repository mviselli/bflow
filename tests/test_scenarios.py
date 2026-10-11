"""Ready scenarios: actions at known ticks, reproducible, each with its story."""

from dataclasses import replace

import pytest

from bflow.core.engine import Engine
from bflow.core.layout import default_layout
from bflow.core.scenarios import (
    PEAK_RATE_BAGS_S, SCENARIOS, Scenario, ScheduledAction, fault_scenario, peak_scenario,
)
from tests.test_plant import PlantChecker, halted_belts


def scenario_engine(scenario):
    return Engine(scenario.layout, seed=scenario.seed, actions=scenario.actions)


def by_hand(engine, scenario):
    """Sends the scenario's actions due at this tick as operator commands."""
    for action in scenario.actions:
        if action.tick == engine.tick:
            args = (action.target_id,) if action.value is None else (action.target_id, action.value)
            getattr(engine, action.action)(*args)


def run_checked(scenario, ticks):
    """The scenario with its actions sent by hand, every tick under the checker."""
    engine = Engine(scenario.layout, seed=scenario.seed)
    checker = PlantChecker(engine)
    for _ in range(ticks):
        by_hand(engine, scenario)
        checker.halted = halted_belts(engine)
        engine.step()
        checker.check()
    return checker


def state(engine):
    """Everything a run is judged by: counters, bags on the belts and events."""
    return (engine.stats(),
            [(bag.id, bag.conveyor_id, bag.position_m) for conveyor in engine.conveyors.values()
             for bag in conveyor.baggage],
            [(event.id, event.tick, event.kind, event.element_id, event.alarm_id)
             for event in engine.events.recent])


@pytest.mark.parametrize("name", SCENARIOS)
def test_scheduled_actions_give_the_same_run_as_the_same_commands_sent_by_hand(name):
    scenario = SCENARIOS[name]
    scheduled, manual = scenario_engine(scenario), Engine(scenario.layout, seed=scenario.seed)
    for _ in range(6000):
        by_hand(manual, scenario)
        scheduled.step()
        manual.step()
    assert state(scheduled) == state(manual)
    assert scheduled.stats().generated > 0


@pytest.mark.parametrize("name", SCENARIOS)
def test_a_scenario_is_reproducible(name):
    first, second = scenario_engine(SCENARIOS[name]), scenario_engine(SCENARIOS[name])
    for _ in range(3000):
        first.step()
        second.step()
    assert state(first) == state(second)


def test_an_action_applies_at_the_start_of_the_step_after_its_tick():
    engine = Engine(default_layout(), actions=(ScheduledAction(3, "fault_belt", "line-1"),))
    for _ in range(3):
        engine.step()
    assert not engine.conveyors["line-1"].faulty
    engine.step()
    assert engine.conveyors["line-1"].faulty
    # Its event carries the tick it was due at, like a command sent then.
    assert [(event.tick, event.kind) for event in engine.events.recent] == [(3, "belt_fault")]


def test_an_action_at_tick_zero_applies_in_the_first_step():
    engine = Engine(default_layout(), actions=(ScheduledAction(0, "stop_belt", "line-1"),))
    engine.step()
    assert engine.conveyors["line-1"].stopped


def test_normal_traffic_runs_ten_minutes_with_no_queue_warning_or_error():
    checker = run_checked(SCENARIOS["normal"], 12000)
    stats = checker.engine.stats()
    assert stats.waiting == 0
    assert (stats.errors, stats.warnings, stats.misdelivered) == (0, 0, 0)
    assert "entrance_queue_started" not in checker.event_counts
    assert all(node.correctly_delivered > 0 for node in stats.outputs)


def test_the_peak_queues_the_upstream_desks_and_everything_clears_within_ten_minutes():
    checker = run_checked(peak_scenario(), 12000)
    engine, first, last = checker.engine, checker.first_tick, checker.last_tick
    # Six rate changes when the peak starts, six when it ends.
    assert checker.event_counts["input_rate_changed"] == 12
    assert (first["input_rate_changed"], last["input_rate_changed"]) == (1200, 3600)
    # Nothing queues or warns before the peak; during it the line congests
    # and the desks queue.
    assert 1200 < first["congestion_started"] < 3600
    assert 1200 < first["entrance_queue_started"] < 3600
    # After the peak, every queue and every warning clears before 600 s.
    stats = engine.stats()
    assert stats.waiting == 0
    assert stats.congestions > 0 and stats.active_warnings == 0
    assert checker.event_counts["entrance_queue_cleared"] == checker.event_counts[
        "entrance_queue_started"]
    assert last["congestion_cleared"] < 12000
    assert all(engine.arrival_rates[node.id] == node.arrival_rate_bags_s
               for node in engine.layout.inputs)


def test_at_the_end_of_the_peak_only_the_upstream_desks_have_queues():
    # The desk joining nearest the sort line gets half of its island's share,
    # enough for the peak rate; the two upstream desks collect the backlog.
    engine = scenario_engine(peak_scenario())
    for _ in range(3600):
        engine.step()
    waiting = {node.input_id: node.waiting for node in engine.stats().inputs}
    assert all(waiting[input_id] > 0 for input_id in ("input-a1", "input-a2", "input-b1", "input-b2"))
    assert waiting["input-a3"] == waiting["input-b3"] == 0


def test_the_peak_rate_is_above_what_the_sort_line_can_carry():
    layout = default_layout()
    line = next(belt for belt in layout.belts if belt.id == "line-1")
    line_capacity = line.speed_m_s / (layout.baggage_length_m + layout.min_gap_m)
    normal = sum(node.arrival_rate_bags_s for node in layout.inputs)
    assert normal < line_capacity < PEAK_RATE_BAGS_S * len(layout.inputs)


def test_the_fault_halts_line_2_at_sixty_seconds_and_backs_up_the_whole_plant():
    checker = run_checked(fault_scenario(), 12000)
    engine = checker.engine
    assert checker.first_tick["belt_fault"] == 1200
    assert checker.event_counts["belt_fault"] == 1
    stats = engine.stats()
    # The fault waits for the operator: still active at the end, every desk queued.
    assert engine.conveyors["line-2"].faulty
    assert stats.active_errors == 1 and stats.faults == 1
    assert all(node.waiting > 0 for node in stats.inputs)
    assert stats.throughput == 0


def test_the_operator_can_repair_the_scheduled_fault_and_the_plant_recovers():
    engine = scenario_engine(fault_scenario())
    for _ in range(4800):
        engine.step()
    engine.repair_belt("line-2")
    while engine.waiting_count or engine.alarms:
        assert engine.tick < 40000
        engine.step()
    assert engine.stats().is_conserved


def test_scheduled_actions_reject_bad_values():
    with pytest.raises(ValueError, match="tick"):
        ScheduledAction(-1, "fault_belt", "line-1")
    with pytest.raises(ValueError, match="tick"):
        ScheduledAction(1.5, "fault_belt", "line-1")
    with pytest.raises(ValueError, match="Unknown scheduled action"):
        ScheduledAction(0, "acknowledge_alarm", "line-1")
    with pytest.raises(ValueError, match="needs a value"):
        ScheduledAction(0, "set_arrival_rate", "input-a1")
    with pytest.raises(ValueError, match="takes no value"):
        ScheduledAction(0, "fault_belt", "line-1", 1.0)
    with pytest.raises(ValueError, match="value"):
        ScheduledAction(0, "set_arrival_rate", "input-a1", -0.1)


def test_actions_on_elements_not_in_the_layout_are_rejected_before_the_run():
    on_input = ScheduledAction(0, "set_arrival_rate", "line-1", 0.2)
    on_belt = ScheduledAction(0, "fault_belt", "input-a1")
    for action in (on_input, on_belt):
        with pytest.raises(ValueError, match="unknown id"):
            Engine(default_layout(), actions=(action,))
        with pytest.raises(ValueError, match="unknown id"):
            replace(SCENARIOS["normal"], actions=(action,))


def test_scenarios_have_distinct_ids_and_run_the_demo_plant():
    assert list(SCENARIOS) == ["normal", "peak", "fault"]
    for scenario_id, scenario in SCENARIOS.items():
        assert isinstance(scenario, Scenario) and scenario.id == scenario_id
        assert scenario.layout == default_layout()


@pytest.mark.parametrize("name", SCENARIOS)
def test_charts_kpis_and_events_describe_the_same_run(name):
    # Ten minutes of each scenario. Independently of the engine's counters,
    # the events are replayed (open queues, faults, warnings) and the bags
    # leaving the plant are counted; at every sample the chart's values, the
    # indicators and those two accounts must agree.
    engine = scenario_engine(SCENARIOS[name])
    last_event_id = 0
    open_queues, open_faults, open_warnings = set(), set(), set()
    by_severity = {"error": 0, "warning": 0}
    delivered_at = []  # ticks of the correct deliveries
    wrong_exits = 0
    samples_checked = 0
    for _ in range(12000):
        engine.step()
        for event in engine.events.since(last_event_id):
            last_event_id = event.id
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
            subject = event.baggage_id or event.element_id
            if event.kind == "entrance_queue_started":
                open_queues.add(subject)
            elif event.kind == "entrance_queue_cleared":
                open_queues.remove(subject)
            elif event.kind == "belt_fault":
                open_faults.add(subject)
            elif event.kind == "belt_repaired":
                open_faults.remove(subject)
            elif event.kind in ("congestion_started", "prolonged_wait_started"):
                open_warnings.add((event.kind, subject))
            elif event.kind == "congestion_cleared":
                open_warnings.remove(("congestion_started", subject))
            elif event.kind == "prolonged_wait_resolved":
                open_warnings.remove(("prolonged_wait_started", subject))
        for bag in engine.exited_this_tick:
            if bag.missorted_to_id is None:
                delivered_at.append(engine.tick)
            else:
                wrong_exits += 1
        sample, stats = engine.series[-1], engine.stats()
        if sample.tick != engine.tick:
            continue
        samples_checked += 1
        # The chart's point is the indicators at the same tick.
        assert (sample.time_s, sample.in_transit, sample.waiting, sample.correctly_delivered,
                sample.misdelivered, sample.throughput) == (
            stats.time_s, stats.in_transit, stats.waiting, stats.correctly_delivered,
            stats.misdelivered, stats.throughput)
        # ... and what the events and the exits say happened.
        assert (sample.waiting > 0) == bool(open_queues)
        assert {node.input_id for node in stats.inputs if node.waiting} == open_queues
        assert sample.correctly_delivered == len(delivered_at)
        assert sample.misdelivered == wrong_exits
        assert sample.throughput == sum(tick > engine.tick - 1200 for tick in delivered_at)
        assert (stats.active_errors, stats.active_warnings) == (len(open_faults), len(open_warnings))
        assert (stats.errors, stats.warnings) == (by_severity["error"], by_severity["warning"])
    assert samples_checked == 600
