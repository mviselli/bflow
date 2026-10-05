"""Congestion warning: a belt above 80 % full for 10 simulated seconds.

It clears only below 60 %, so a belt hovering around the threshold does not
start and clear a warning at every tick. The minimal belt holds 12 bags:
10 are above 80 %, 9 are not; 8 keep a congestion, 7 clear it.
"""

from dataclasses import replace

from bflow.core.engine import CONGESTION_DELAY_TICKS, Engine
from bflow.core.events import Severity
from bflow.core.layout import minimal_layout
from bflow.core.models import Baggage
from tests.layouts import compact_layout


def stopped_belt_with(count):
    """The minimal belt, stopped, with ``count`` bags one gap apart and no arrivals."""
    engine = Engine(minimal_layout(arrival_rate_bags_s=0))
    assert engine.belt_capacities["belt-1"] == 12
    conveyor = engine.conveyors["belt-1"]
    for index in reversed(range(count)):
        conveyor.baggage.append(Baggage(f"bag-{index}", "output-1", 0.6, 0, "belt-1",
                                        index * 0.8, entered_at_s=0))
    conveyor.baggage.reverse()
    engine.stop_belt("belt-1")
    return engine, conveyor


def advance(engine, ticks):
    for _ in range(ticks):
        engine.step()


def congestion_warnings(engine):
    """Congestion warnings among all warnings (bags held still also warn after 30 s)."""
    warnings = [event.kind for event in engine.events.recent if event.severity == Severity.WARNING]
    assert len(warnings) == engine.stats().warnings  # nothing dropped from the history
    return warnings.count("congestion_started")


def congestion_events(engine):
    return [(event.tick, event.severity, event.kind, event.element_id)
            for event in engine.events.recent if event.kind.startswith("congestion")]


def test_a_belt_above_80_percent_becomes_congested_after_exactly_10_seconds():
    engine, conveyor = stopped_belt_with(10)
    assert CONGESTION_DELAY_TICKS == 200
    # Above 80 % from tick 1: still not congested after 200 ticks (9.95 s above).
    advance(engine, 200)
    assert not conveyor.congested
    engine.step()
    assert conveyor.congested
    assert congestion_events(engine) == [(201, Severity.WARNING, "congestion_started", "belt-1")]
    assert congestion_warnings(engine) == 1
    advance(engine, 1000)
    assert congestion_warnings(engine) == 1  # one warning per start, not per tick


def test_exactly_80_percent_or_less_never_congests():
    engine, conveyor = stopped_belt_with(9)
    advance(engine, 2000)
    assert not conveyor.congested
    assert congestion_events(engine) == []


def test_dropping_to_80_percent_restarts_the_10_seconds():
    engine, conveyor = stopped_belt_with(10)
    advance(engine, 150)
    removed = conveyor.baggage.pop(0)
    engine.step()  # 9 bags: the time above 80 % starts again
    conveyor.baggage.insert(0, removed)
    advance(engine, 200)
    assert not conveyor.congested
    engine.step()
    assert conveyor.congested
    assert congestion_events(engine)[0][0] == 352


def test_congestion_clears_only_below_60_percent():
    engine, conveyor = stopped_belt_with(10)
    advance(engine, 201)
    del conveyor.baggage[:2]  # 8 of 12: below 80 %, not below 60 %
    advance(engine, 500)
    assert conveyor.congested
    del conveyor.baggage[0]  # 7 of 12
    engine.step()
    assert not conveyor.congested
    assert congestion_events(engine) == [
        (201, Severity.WARNING, "congestion_started", "belt-1"),
        (702, Severity.INFO, "congestion_cleared", "belt-1"),
    ]
    # The clearing is information: still one warning.
    assert congestion_warnings(engine) == 1


def test_a_new_congestion_after_clearing_is_a_new_warning():
    engine, conveyor = stopped_belt_with(10)
    advance(engine, 201)
    kept = conveyor.baggage[:3]
    del conveyor.baggage[:3]
    engine.step()
    conveyor.baggage[:0] = kept
    advance(engine, 201)
    assert [kind for _, _, kind, _ in congestion_events(engine)] == [
        "congestion_started", "congestion_cleared", "congestion_started"]
    assert congestion_warnings(engine) == 2


def test_no_congestion_without_stepping_so_a_pause_freezes_the_time():
    engine, conveyor = stopped_belt_with(10)
    advance(engine, 150)
    # A paused runner does not step: the 150 ticks above 80 % are kept, and
    # 51 more are needed whenever the run resumes.
    advance(engine, 50)
    assert not conveyor.congested
    engine.step()
    assert conveyor.congested


def test_saturated_inputs_congest_the_feeders_with_one_warning_each():
    layout = compact_layout()
    engine = Engine(replace(layout, inputs=tuple(replace(node, arrival_rate_bags_s=1)
                                                 for node in layout.inputs)))
    advance(engine, 3000)
    started = [event.element_id for event in engine.events.recent
               if event.kind == "congestion_started"]
    assert {"feeder-a-1", "feeder-b", "feeder-c-1"} <= set(started)
    assert len(started) == len(set(started))
