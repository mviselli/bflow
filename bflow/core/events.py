"""Engine events with progressive identifiers and a bounded history.

An event describes a change, not a repeated state: for a condition the start
and the resolution are recorded, never an identical event at every tick.
Per-severity counts are cumulative and do not depend on the retained history,
which keeps only the most recent events.
"""

from collections import deque
from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    """Event that happened at the given tick, with simulated time and severity.

    ``kind`` is a stable code for programs and tests; ``message`` is the text
    shown to the operator. ``element_id`` and ``baggage_id`` identify the
    plant element or bag involved, when there is one.
    """

    id: int
    tick: int
    time_s: float
    severity: Severity
    kind: str
    message: str
    element_id: str | None = None
    baggage_id: str | None = None


class EventLog:
    """Event log of a single run.

    Identifiers start at 1 and never repeat: a reader can ask only for the
    events after the last one it received with since().
    """

    def __init__(self, max_recent: int = 100) -> None:
        if isinstance(max_recent, bool) or not isinstance(max_recent, int) or max_recent < 1:
            raise ValueError("max_recent must be a positive integer")
        self.recent: deque[Event] = deque(maxlen=max_recent)
        self.counts = {severity: 0 for severity in Severity}
        self._last_id = 0

    @property
    def last_id(self) -> int:
        """Identifier of the last recorded event, zero if there is none."""
        return self._last_id

    @property
    def total_count(self) -> int:
        """All recorded events, including those dropped from the history."""
        return self._last_id

    def record(
        self,
        tick: int,
        time_s: float,
        severity: Severity,
        kind: str,
        message: str,
        *,
        element_id: str | None = None,
        baggage_id: str | None = None,
    ) -> Event:
        self._last_id += 1
        event = Event(self._last_id, tick, time_s, Severity(severity), kind, message,
                      element_id, baggage_id)
        self.recent.append(event)
        self.counts[event.severity] += 1
        return event

    def since(self, event_id: int) -> tuple[Event, ...]:
        """Retained events with an identifier greater than event_id."""
        return tuple(event for event in self.recent if event.id > event_id)
