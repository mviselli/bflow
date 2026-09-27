"""Engine data, with no dependency on the server or graphics.

Distances are in metres and timestamps in simulated seconds, never real time.
The position is the rear edge of the bag: on the belt it occupies
``[position_m, position_m + length_m]``. Admission happens at position zero;
the front edge reaches the end of the belt at the conveyor's ``length_m``.

The plant configuration is in layout.py and immutable; bags and belt
contents are mutable state. Checks at construction time do not replace those
the engine must apply during movement, admission and transfers.
"""

from dataclasses import dataclass, field

from bflow.core.checks import check_identifier, check_quantity
from bflow.core.layout import BeltConfig


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
        check_identifier("id", self.id)
        check_identifier("destination_id", self.destination_id)
        check_quantity("length_m", self.length_m, positive=True)
        check_quantity("position_m", self.position_m)
        check_quantity("generated_at_s", self.generated_at_s)
        if self.conveyor_id is not None:
            check_identifier("conveyor_id", self.conveyor_id)
        if self.entered_at_s is None:
            if self.conveyor_id is not None or self.exited_at_s is not None:
                raise ValueError("A bag that was not admitted cannot be on a belt or exited")
            if self.position_m != 0:
                raise ValueError("A waiting bag must be at position zero")
        else:
            check_quantity("entered_at_s", self.entered_at_s)
            if self.entered_at_s < self.generated_at_s:
                raise ValueError("Admission cannot precede generation")
            if self.exited_at_s is None:
                if self.conveyor_id is None:
                    raise ValueError("A bag in transit must be on a belt")
            else:
                check_quantity("exited_at_s", self.exited_at_s)
                if self.exited_at_s < self.entered_at_s:
                    raise ValueError("Exit cannot precede admission")
                if self.conveyor_id is not None:
                    raise ValueError("An exited bag cannot be on a belt")


@dataclass
class Conveyor:
    """Belt state, with bags ordered from the entrance towards the exit.

    The engine maintains the order, membership and spacing of the list.
    The configuration stays separate from the state so it can be reset.
    """

    config: BeltConfig
    baggage: list[Baggage] = field(default_factory=list)
