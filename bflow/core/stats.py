"""Riepilogo immutabile delle statistiche, calcolato solo dal motore.

CLI e GUI mostrano questi valori senza ricostruire una propria versione dei
conteggi. Il riepilogo è una fotografia: non cambia quando il motore avanza.
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
        """Nessun bagaglio perso o duplicato, né all'ingresso né nell'impianto."""
        return (
            self.generated == self.admitted + self.waiting
            and self.admitted == self.correctly_delivered + self.misdelivered + self.in_transit
        )
