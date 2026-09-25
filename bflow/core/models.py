"""Engine data, with no dependency on the server or graphics.

Distances are in metres and timestamps in simulated seconds, never real time.
The position is the rear edge of the bag: on the belt it occupies
``[position_m, position_m + length_m]``. Admission happens at position zero;
the front edge reaches the end of the belt at the conveyor's ``length_m``.

Configurations are immutable; bags and belt contents are mutable state.
Checks at construction time do not replace those the engine must apply
during movement, admission and transfers.
"""

from dataclasses import dataclass, field
from math import isfinite


def _identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identifier")


def _quantity(name: str, value: float, *, positive: bool = False) -> None:
    if not isfinite(value) or value < 0 or (positive and value == 0):
        bound = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {bound}")


@dataclass
class Baggage:
    """A bag that is waiting, admitted or exited.

    ``destination_id`` is the intended output and does not change with sorting.
    Before admission ``conveyor_id`` and ``entered_at_s`` are None.
    After exit ``conveyor_id`` is None again and ``exited_at_s`` is set;
    ``position_m`` keeps the last position. Travel time starts at
    ``entered_at_s``, excluding the wait at the entrance.
    """

    id: str
    destination_id: str
    length_m: float
    generated_at_s: float
    conveyor_id: str | None = None
    position_m: float = 0.0
    entered_at_s: float | None = None
    exited_at_s: float | None = None

    def __post_init__(self) -> None:
        _identifier("id", self.id)
        _identifier("destination_id", self.destination_id)
        _quantity("length_m", self.length_m, positive=True)
        _quantity("position_m", self.position_m)
        _quantity("generated_at_s", self.generated_at_s)
        if self.conveyor_id is not None:
            _identifier("conveyor_id", self.conveyor_id)
        if self.entered_at_s is None:
            if self.conveyor_id is not None or self.exited_at_s is not None:
                raise ValueError("A bag that was not admitted cannot be on a belt or exited")
            if self.position_m != 0:
                raise ValueError("A waiting bag must be at position zero")
        else:
            _quantity("entered_at_s", self.entered_at_s)
            if self.entered_at_s < self.generated_at_s:
                raise ValueError("Admission cannot precede generation")
            if self.exited_at_s is None:
                if self.conveyor_id is None:
                    raise ValueError("A bag in transit must be on a belt")
            else:
                _quantity("exited_at_s", self.exited_at_s)
                if self.exited_at_s < self.entered_at_s:
                    raise ValueError("Exit cannot precede admission")
                if self.conveyor_id is not None:
                    raise ValueError("An exited bag cannot be on a belt")


@dataclass(frozen=True)
class ConveyorConfig:
    """Physical parameters of a belt; the nominal speed is strictly positive."""

    id: str = "belt-1"
    length_m: float = 10.0
    speed_m_s: float = 1.0

    def __post_init__(self) -> None:
        _identifier("id", self.id)
        _quantity("length_m", self.length_m, positive=True)
        _quantity("speed_m_s", self.speed_m_s, positive=True)


@dataclass
class Conveyor:
    """Belt state, with bags ordered from the entrance towards the exit.

    The engine maintains the order, membership and spacing of the list.
    The configuration stays separate from the state so it can be reset.
    """

    config: ConveyorConfig
    baggage: list[Baggage] = field(default_factory=list)


@dataclass(frozen=True)
class SimulationConfig:
    """Minimal route: input_id → conveyor.id → output_id.

    Every bag is destined for output_id. A zero rate disables generation;
    min_gap_m is the free space between two bags, beyond their length.
    The full topology and graphical geometry will be defined in the layout.
    """

    input_id: str = "input-a"
    output_id: str = "output-1"
    conveyor: ConveyorConfig = field(default_factory=ConveyorConfig)
    arrival_rate_bags_s: float = 0.5
    baggage_length_m: float = 0.6
    min_gap_m: float = 0.2

    def __post_init__(self) -> None:
        _identifier("input_id", self.input_id)
        _identifier("output_id", self.output_id)
        if len({self.input_id, self.conveyor.id, self.output_id}) != 3:
            raise ValueError("Input, conveyor and output must have distinct identifiers")
        _quantity("arrival_rate_bags_s", self.arrival_rate_bags_s)
        _quantity("baggage_length_m", self.baggage_length_m, positive=True)
        _quantity("min_gap_m", self.min_gap_m)
        if self.baggage_length_m > self.conveyor.length_m:
            raise ValueError("The bag must fit on the belt")
