"""Motore a passo fisso, eseguibile senza server e senza attese reali."""

from random import Random

from bflow.core.models import Conveyor, SimulationConfig


STEP_MS = 50
STEP_SECONDS = STEP_MS / 1000


class Engine:
    """Possiede configurazione, stato e generatore casuale della singola run.

    Il tick conta i passi completati: lo stato iniziale è al tick 0, tempo 0.
    Ogni chiamata a step() completa esattamente 50 ms simulati. Il chiamante
    decide quando eseguirla: pausa e velocità reale non cambiano il passo.
    Il tempo deriva dai tick interi, evitando errori da somme ripetute di 0.05.

    Tutte le future estrazioni del motore devono usare rng, mai il generatore
    globale del modulo random. Stesso seed e stesse operazioni riproducono la
    sequenza senza interferenze fra istanze. Generazione e movimento saranno
    aggiunti a step(); per ora avanza soltanto l'orologio della run vuota.
    """

    def __init__(self, config: SimulationConfig | None = None, *, seed: int = 42) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed deve essere un numero intero")
        self.config = config if config is not None else SimulationConfig()
        self.seed = seed
        self.rng = Random(seed)
        self.conveyor = Conveyor(self.config.conveyor)
        self._tick = 0

    @property
    def tick(self) -> int:
        """Numero di passi completati, inizialmente zero."""
        return self._tick

    @property
    def time_s(self) -> float:
        """Tempo simulato in secondi, calcolato senza accumulare arrotondamenti."""
        return self._tick * STEP_MS / 1000

    def step(self) -> None:
        """Completa un passo fisso senza consultare il tempo reale o attendere."""
        self._tick += 1
