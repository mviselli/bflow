"""Contratto dei dati fisici e del ciclo di vita, prima del motore."""

from dataclasses import FrozenInstanceError

import pytest

from bflow.core.models import Baggage, Conveyor, ConveyorConfig, SimulationConfig


def test_waiting_transit_and_exit_keep_simulated_times_distinct():
    fields = dict(id="bag-1", destination_id="output-1", length_m=0.6, generated_at_s=2)
    waiting = Baggage(**fields)
    transit = Baggage(**fields, conveyor_id="belt-1", entered_at_s=5, position_m=3)
    delivered = Baggage(**fields, entered_at_s=5, exited_at_s=15, position_m=9.4)

    assert waiting.entered_at_s is None
    assert waiting.conveyor_id is None
    assert transit.position_m + transit.length_m == pytest.approx(3.6)
    assert delivered.exited_at_s - delivered.entered_at_s == 10
    assert delivered.destination_id == waiting.destination_id
    assert delivered.conveyor_id is None


def test_conveyors_do_not_share_mutable_contents():
    config = ConveyorConfig()
    first, second = Conveyor(config), Conveyor(config)
    first.baggage.append(Baggage("bag-1", "output-1", 0.6, 0, config.id, entered_at_s=0))
    assert second.baggage == []
    with pytest.raises(FrozenInstanceError):
        config.speed_m_s = 2
    with pytest.raises(FrozenInstanceError):
        SimulationConfig().min_gap_m = 1


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["length_m", "speed_m_s"])
def test_invalid_conveyor_physics(field, value):
    with pytest.raises(ValueError, match=field):
        ConveyorConfig(**{field: value})


@pytest.mark.parametrize("fields", [
    {"id": " "}, {"destination_id": ""}, {"length_m": 0},
    {"position_m": -1}, {"generated_at_s": float("nan")},
    {"conveyor_id": "belt-1"}, {"position_m": 1},
    {"exited_at_s": 3}, {"entered_at_s": 1},
    {"entered_at_s": 1, "conveyor_id": "belt-1"},
    {"entered_at_s": 3, "exited_at_s": 2},
    {"entered_at_s": 3, "exited_at_s": 4, "conveyor_id": "belt-1"},
    {"entered_at_s": float("inf"), "conveyor_id": "belt-1"},
    {"entered_at_s": 3, "exited_at_s": float("nan")},
])
def test_invalid_baggage_lifecycle(fields):
    values = dict(id="bag-1", destination_id="output-1", length_m=0.6, generated_at_s=2)
    with pytest.raises(ValueError):
        Baggage(**(values | fields))


@pytest.mark.parametrize("fields", [
    {"input_id": ""}, {"output_id": "input-a"}, {"input_id": "belt-1"},
    {"arrival_rate_bags_s": -1}, {"arrival_rate_bags_s": float("inf")},
    {"min_gap_m": -0.1}, {"baggage_length_m": 0}, {"baggage_length_m": 11},
])
def test_invalid_minimal_configuration(fields):
    with pytest.raises(ValueError):
        SimulationConfig(**fields)


def test_boundary_configuration_allows_no_arrivals_no_gap_and_exact_fit():
    config = SimulationConfig(arrival_rate_bags_s=0, min_gap_m=0, baggage_length_m=10)
    assert config.baggage_length_m == config.conveyor.length_m


@pytest.mark.parametrize("field", ["length_m", "speed_m_s"])
def test_conveyor_requires_positive_dimensions_and_nominal_speed(field):
    with pytest.raises(ValueError, match=field):
        ConveyorConfig(**{field: 0})
