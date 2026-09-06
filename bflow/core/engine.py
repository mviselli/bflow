"""Motore a passo fisso, eseguibile senza server e senza attese reali."""

from collections import deque
from random import Random

from bflow.core.models import Baggage, Conveyor, SimulationConfig


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
    sequenza senza interferenze fra istanze. Gli arrivi sono regolari, al ritmo
    configurato, e rilevati alla fine del tick: nel percorso minimo non servono
    estrazioni casuali perché esiste una sola destinazione. Il movimento sarà
    aggiunto successivamente, prima dell'ammissione dei nuovi bagagli.
    """

    def __init__(self, config: SimulationConfig | None = None, *, seed: int = 42) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed deve essere un numero intero")
        self.config = config if config is not None else SimulationConfig()
        self.seed = seed
        self.rng = Random(seed)
        self.conveyor = Conveyor(self.config.conveyor)
        self._tick = 0
        self.waiting: deque[Baggage] = deque()
        self.generated_count = 0
        self.admitted_count = 0

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
        self._generate()
        self._admit()

    def _generate(self) -> None:
        """Accoda tutti gli arrivi dovuti, senza perdere domanda se il nastro è pieno.

        Il totale deriva dal tempo trascorso, senza arrotondare un intervallo
        ai tick né accumulare frazioni a ogni passo. Il primo arrivo avviene
        dopo un intervallo completo. Il timestamp è quello del tick in cui
        l'arrivo viene rilevato (ritardo inferiore a un passo).
        """
        due_count = int(self.tick * STEP_MS * self.config.arrival_rate_bags_s / 1000)
        while self.generated_count < due_count:
            self.generated_count += 1
            self.waiting.append(Baggage(
                id=f"bag-{self.generated_count}",
                destination_id=self.config.output_id,
                length_m=self.config.baggage_length_m,
                generated_at_s=self.time_s,
            ))

    def _admit(self) -> None:
        """Ammette il primo bagaglio in attesa se l'ingresso è libero.

        La lista del nastro è ordinata dall'ingresso all'uscita: il primo
        elemento è il più vicino al nuovo bagaglio. Basta una ammissione per
        tick perché il nuovo bagaglio occupa subito la posizione zero.
        """
        if not self.waiting:
            return
        baggage = self.waiting[0]
        if baggage.length_m > self.conveyor.config.length_m:
            return
        if self.conveyor.baggage:
            nearest = self.conveyor.baggage[0]
            if nearest.position_m < baggage.length_m + self.config.min_gap_m:
                return
        self.waiting.popleft()
        baggage.conveyor_id = self.conveyor.config.id
        baggage.entered_at_s = self.time_s
        baggage.position_m = 0.0
        self.conveyor.baggage.insert(0, baggage)
        self.admitted_count += 1
