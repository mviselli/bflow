"""Immutable statistics summary, computed only by the engine.

The CLI and GUI display these values without rebuilding their own version of
the counts. The summary is a snapshot: it does not change as the engine steps.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BeltStats:
    """How full one belt is. ``capacity`` is the most bags it can hold with the gap."""

    belt_id: str
    bags: int
    capacity: int

    @property
    def occupancy(self) -> float:
        """Share of the capacity occupied by bags, from 0 to 1."""
        return self.bags / self.capacity


@dataclass(frozen=True)
class InputStats:
    """Bags generated at one input and still waiting to be admitted."""

    input_id: str
    waiting: int


@dataclass(frozen=True)
class OutputStats:
    """Bags that arrived at one output: for it, or for another output."""

    output_id: str
    correctly_delivered: int
    misdelivered: int


@dataclass(frozen=True)
class Stats:
    """The counters at one tick. ``belts``, ``inputs`` and ``outputs`` are in layout order.

    ``throughput`` counts the correct deliveries in the last 60 simulated
    seconds (fewer seconds at the start of a run).

    ``errors`` and ``warnings`` are occurrences since the start of the run:
    errors are faults plus wrong sortings, warnings are congestions plus
    prolonged waits. ``active_errors`` and ``active_warnings`` are the
    alarms open now (active or acknowledged), which go back down when their
    conditions end.
    """

    tick: int
    time_s: float
    generated: int
    waiting: int
    admitted: int
    correctly_delivered: int
    misdelivered: int
    in_transit: int
    mean_travel_time_s: float | None
    errors: int
    warnings: int
    faults: int
    wrong_sortings: int
    congestions: int
    prolonged_waits: int
    active_errors: int
    active_warnings: int
    throughput: int
    belts: tuple[BeltStats, ...]
    inputs: tuple[InputStats, ...]
    outputs: tuple[OutputStats, ...]

    @property
    def exited(self) -> int:
        return self.correctly_delivered + self.misdelivered

    @property
    def is_conserved(self) -> bool:
        """No bag lost or duplicated, neither at the entrance nor in the plant.

        The per-input, per-belt and per-output counts must also add up to
        the totals.
        """
        return (
            self.generated == self.admitted + self.waiting
            and self.admitted == self.correctly_delivered + self.misdelivered + self.in_transit
            and self.waiting == sum(node.waiting for node in self.inputs)
            and self.in_transit == sum(belt.bags for belt in self.belts)
            and self.correctly_delivered == sum(node.correctly_delivered for node in self.outputs)
            and self.misdelivered == sum(node.misdelivered for node in self.outputs)
        )
