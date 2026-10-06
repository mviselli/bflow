"""Engine events with progressive identifiers and a bounded history, and alarms.

An event describes a change, not a repeated state: for a condition the start
and the resolution are recorded, never an identical event at every tick.
Per-severity counts are cumulative and do not depend on the retained history,
which keeps only the most recent events.

An alarm is a condition that lasts (a fault, a congestion, a prolonged
wait): it is active from its start, acknowledged when the operator has seen
it, and resolved when the condition ends. The engine owns the alarms; each
change of state is also an event.
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
    alarm_id: int | None = None


class AlarmState(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass
class Alarm:
    """A lasting condition of a belt or a bag, raised at ``raised_at_s``.

    ``kind`` is the condition (``belt_fault``, ``congestion`` or
    ``prolonged_wait``). Acknowledging records that the operator has seen
    the alarm: it changes nothing in the plant, so an acknowledged fault
    still needs a repair. Only the end of the condition resolves the alarm,
    acknowledged or not. Times are simulated seconds, so they stand still
    while the simulation is paused.
    """

    id: int
    kind: str
    severity: Severity
    message: str
    element_id: str | None
    baggage_id: str | None
    raised_at_s: float
    acknowledged_at_s: float | None = None
    resolved_at_s: float | None = None

    @property
    def state(self) -> AlarmState:
        if self.resolved_at_s is not None:
            return AlarmState.RESOLVED
        if self.acknowledged_at_s is not None:
            return AlarmState.ACKNOWLEDGED
        return AlarmState.ACTIVE


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
        alarm_id: int | None = None,
    ) -> Event:
        self._last_id += 1
        event = Event(self._last_id, tick, time_s, Severity(severity), kind, message,
                      element_id, baggage_id, alarm_id)
        self.recent.append(event)
        self.counts[event.severity] += 1
        return event

    def since(self, event_id: int) -> tuple[Event, ...]:
        """Retained events with an identifier greater than event_id."""
        return tuple(event for event in self.recent if event.id > event_id)
