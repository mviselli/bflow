"""Immutable statistics summary, computed only by the engine.

The CLI and GUI display these values without rebuilding their own version of
the counts. The summary is a snapshot: it does not change as the engine steps.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Stats:
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

    @property
    def exited(self) -> int:
        return self.correctly_delivered + self.misdelivered

    @property
    def is_conserved(self) -> bool:
        """No bag lost or duplicated, neither at the entrance nor in the plant."""
        return (
            self.generated == self.admitted + self.waiting
            and self.admitted == self.correctly_delivered + self.misdelivered + self.in_transit
        )
