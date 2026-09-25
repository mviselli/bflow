"""Headless CLI: same engine, duration in simulated seconds and summary."""

import pytest

from bflow import cli
from bflow.core.engine import Engine


def test_default_run_lasts_600_seconds_and_is_conserved(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "Seed 42 · 600.00 simulated s (12000 ticks)" in out
    assert "Conservation: OK" in out


def test_summary_matches_the_engine_after_the_same_steps(capsys):
    assert cli.main(["--duration", "30.5", "--seed", "7"]) == 0
    engine = Engine(seed=7)
    for _ in range(610):
        engine.step()
    assert capsys.readouterr().out.strip() == cli.format_summary(engine.stats(), 7)


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
