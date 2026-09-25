"""Eventi del motore con identificativi progressivi e cronologia limitata.

Un evento descrive un cambiamento, non uno stato ripetuto: per una condizione
si registrano l'inizio e la risoluzione, mai un evento identico a ogni tick.
I conteggi per gravità sono cumulativi e non dipendono dalla cronologia
conservata, che mantiene solo gli eventi più recenti.
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
    """Evento avvenuto al tick indicato, con tempo simulato e gravità.

    ``kind`` è un codice stabile per programmi e test; ``message`` è il testo
    da mostrare all'operatore. ``element_id`` e ``baggage_id`` indicano
    l'elemento dell'impianto o il bagaglio coinvolto, se presenti.
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
    """Registro degli eventi della singola run.

    Gli identificativi partono da 1 e non si ripetono: chi legge può chiedere
    solo gli eventi successivi all'ultimo ricevuto con since().
    """

    def __init__(self, max_recent: int = 100) -> None:
        if isinstance(max_recent, bool) or not isinstance(max_recent, int) or max_recent < 1:
            raise ValueError("max_recent deve essere un intero positivo")
        self.recent: deque[Event] = deque(maxlen=max_recent)
        self.counts = {severity: 0 for severity in Severity}
        self._last_id = 0

    @property
    def last_id(self) -> int:
        """Identificativo dell'ultimo evento registrato, zero se nessuno."""
        return self._last_id

    @property
    def total_count(self) -> int:
        """Tutti gli eventi registrati, anche quelli usciti dalla cronologia."""
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
        """Eventi conservati con identificativo maggiore di event_id."""
        return tuple(event for event in self.recent if event.id > event_id)
