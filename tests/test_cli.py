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
    for element_id in ("input-a", "input-c", "output-1", "output-3", "collector", "branch-3-2"):
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
