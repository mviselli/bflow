"""Headless CLI: same engine, duration in simulated seconds and summary."""

import pytest

from bflow import cli
from bflow.core.engine import Engine
from bflow.core.layout import default_layout, minimal_layout


def test_default_run_is_the_full_plant_for_600_seconds_and_is_conserved(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "Layout full · seed 42 · 600.00 simulated s (12000 ticks)" in out
    assert "Conservation: OK" in out
    for element_id in ("input-a1", "input-b3", "output-1", "output-4", "island-b-4", "line-4"):
        assert f"  {element_id} " in out


@pytest.mark.parametrize("name, layout", [("full", default_layout), ("minimal", minimal_layout)])
def test_summary_matches_the_engine_after_the_same_steps(name, layout, capsys):
    assert cli.main(["--duration", "30.5", "--seed", "7", "--layout", name]) == 0
    engine = Engine(layout(), seed=7)
    for _ in range(610):
        engine.step()
    assert capsys.readouterr().out.strip() == cli.format_summary(engine.stats(), 7, name)


def test_summary_lists_each_input_output_and_belt_as_counted_by_the_engine(capsys):
    assert cli.main(["--duration", "300"]) == 0
    out = capsys.readouterr().out
    engine = Engine(default_layout())
    for _ in range(6000):
        engine.step()
    stats = engine.stats()
    assert f"Throughput (60 s):   {stats.throughput}" in out
    for node in stats.outputs:
        assert f"{node.output_id:<10} {node.correctly_delivered:>5} {node.misdelivered:>5}" in out
    for belt in stats.belts:
        assert f"{belt.belt_id:<10} {belt.bags:>5} / {belt.capacity:<3}" in out


def test_a_wrong_sorting_probability_causes_errors_and_wrong_exits(capsys):
    assert cli.main(["--duration", "300", "--missort-probability", "0.1"]) == 0
    out = capsys.readouterr().out
    engine = Engine(default_layout())
    engine.set_missort_probability(0.1)
    for _ in range(6000):
        engine.step()
    stats = engine.stats()
    assert stats.errors > 0 and stats.misdelivered > 0
    assert out.strip() == cli.format_summary(stats, 42, "full", 0.1)
    assert "Layout full · seed 42 · wrong sorting 0.1 · 300.00 simulated s" in out
    assert f"Errors:              {stats.errors} (faults 0, wrong sorting {stats.errors})" in out


def test_the_summary_separates_occurrences_from_the_alarms_still_open():
    # line-2 faulty for 60 s, then branch-1 faulty until the end of the run.
    engine = Engine(default_layout())
    for tick in range(4000):
        if tick == 1000:
            engine.fault_belt("line-2")
        if tick == 2200:
            engine.repair_belt("line-2")
        if tick == 3000:
            engine.fault_belt("branch-1")
        engine.step()
    stats = engine.stats()
    lines = cli.format_summary(stats, 42).splitlines()
    assert "Errors:              2 (faults 2, wrong sorting 0)" in lines
    assert (f"Warnings:            {stats.warnings} (congestion {stats.congestions}, "
            f"prolonged wait {stats.prolonged_waits})") in lines
    assert stats.warnings > 0 and stats.active_warnings > 0
    assert f"Active alarms:       errors 1, warnings {stats.active_warnings}" in lines


@pytest.mark.parametrize("probability", ["-0.1", "1.5", "lots"])
def test_invalid_probabilities_are_rejected(probability, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--missort-probability", probability])
    assert error.value.code == 2
    assert "--missort-probability" in capsys.readouterr().err


def test_an_unknown_layout_is_rejected(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--layout", "large"])
    assert error.value.code == 2
    assert "--layout" in capsys.readouterr().err


def test_zero_duration_shows_missing_mean(capsys):
    assert cli.main(["--duration", "0"]) == 0
    out = capsys.readouterr().out
    assert "(0 ticks)" in out
    assert "Mean travel time:" in out and "—" in out


@pytest.mark.parametrize("duration", ["-1", "abc", "0.01", "nan", "inf"])
def test_invalid_durations_are_rejected(duration, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--duration", duration])
    assert error.value.code == 2
    assert "duration" in capsys.readouterr().err


def test_failed_conservation_exits_with_error(monkeypatch, capsys):
    monkeypatch.setattr(cli.Stats, "is_conserved", property(lambda self: False))
    assert cli.main(["--duration", "1"]) == 1
    assert "Conservation: FAILED" in capsys.readouterr().out
