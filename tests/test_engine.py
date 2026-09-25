"""Simulated clock and per-run randomness."""

import random

import pytest

from bflow.core.engine import Engine, STEP_SECONDS
from bflow.core.models import ConveyorConfig, SimulationConfig


def test_initial_state_uses_the_supplied_configuration():
    config = SimulationConfig(conveyor=ConveyorConfig(length_m=20))
    engine = Engine(config, seed=7)
    assert engine.tick == 0
    assert engine.time_s == 0
    assert engine.seed == 7
    assert engine.config is config
    assert engine.conveyor.config is config.conveyor
    assert engine.conveyor.baggage == []


def test_each_step_is_fifty_simulated_milliseconds():
    engine = Engine()
    assert STEP_SECONDS == 0.05
    for tick in range(1, 21):
        engine.step()
        assert engine.tick == tick
        assert engine.time_s == tick / 20
    assert engine.time_s == 1


def test_ten_minutes_do_not_accumulate_clock_rounding_errors():
    engine = Engine()
    for _ in range(12_000):
        engine.step()
    assert engine.tick == 12_000
    assert engine.time_s == 600


def test_grouping_steps_does_not_change_simulated_state():
    single, grouped = Engine(seed=9), Engine(seed=9)
    for _ in range(100):
        single.step()
    for _ in range(20):
        for _ in range(5):
            grouped.step()
    assert single.tick == grouped.tick == 100
    assert single.time_s == grouped.time_s == 5
    assert single.conveyor == grouped.conveyor
    assert single.rng.getstate() == grouped.rng.getstate()


def test_seed_reproduces_draws_without_interference_between_runs():
    first, second, other = Engine(seed=42), Engine(seed=42), Engine(seed=43)
    first_draws, second_draws, other_draws = [], [], []
    for _ in range(20):
        first_draws.append(first.rng.random())
        other_draws.append(other.rng.random())
        second_draws.append(second.rng.random())
    assert first_draws == second_draws
    assert first_draws != other_draws


def test_engine_does_not_change_global_random_state():
    before = random.getstate()
    engine = Engine(seed=42)
    engine.rng.random()
    engine.step()
    assert random.getstate() == before


@pytest.mark.parametrize("seed", [None, True, 1.5, "42"])
def test_seed_requires_an_explicit_integer(seed):
    with pytest.raises(ValueError, match="seed"):
        Engine(seed=seed)


@pytest.mark.parametrize("seed", [0, -1, 42])
def test_integer_seeds_are_repeatable(seed):
    assert Engine(seed=seed).rng.getstate() == Engine(seed=seed).rng.getstate()
