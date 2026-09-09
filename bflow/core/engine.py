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
    estrazioni casuali perché esiste una sola destinazione. Il movimento dei
    bagagli già presenti precede l'ammissione dei nuovi bagagli.
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
        self.correctly_delivered_count = 0
        self.misdelivered_count = 0
        self._total_travel_time_s = 0.0
        # Solo le uscite dell’ultimo tick: nessuna cronologia illimitata.
        self.exited_this_tick: tuple[Baggage, ...] = ()

    @property
    def tick(self) -> int:
        """Numero di passi completati, inizialmente zero."""
        return self._tick

    @property
    def time_s(self) -> float:
        """Tempo simulato in secondi, calcolato senza accumulare arrotondamenti."""
        return self._tick * STEP_MS / 1000

    @property
    def exited_count(self) -> int:
        """Tutte le uscite, corrette ed errate, senza un contatore duplicato."""
        return self.correctly_delivered_count + self.misdelivered_count

    @property
    def in_transit_count(self) -> int:
        """Bagagli ancora sul nastro, inclusi quelli fermi; esclusa l'attesa."""
        return len(self.conveyor.baggage)

    @property
    def mean_travel_time_s(self) -> float | None:
        """Media ammissione → uscita, anche errata; None senza campioni.

        CLI e GUI potranno visualizzare None come “—”. Si conserva solo la
        somma dei tempi, non una cronologia crescente dei bagagli usciti.
        """
        if self.exited_count == 0:
            return None
        return self._total_travel_time_s / self.exited_count

    def step(self) -> None:
        """Completa un passo fisso senza consultare il tempo reale o attendere."""
        self._tick += 1
        self._move()
        outgoing = self._evaluate_transfers()
        self._apply_transfers(outgoing)
        self._generate()
        self._admit()

    def _move(self) -> None:
        """Avanza dall'uscita verso l'ingresso, usando la posizione aggiornata davanti.

        Il bordo anteriore si ferma al termine del nastro o al gap minimo dal
        bordo posteriore del bagaglio precedente. La rimozione dei bagagli pronti
        avviene solo dopo aver completato il movimento di tutti i bagagli.
        """
        distance = self.conveyor.config.speed_m_s * STEP_SECONDS
        front_limit = self.conveyor.config.length_m
        for baggage in reversed(self.conveyor.baggage):
            max_position = front_limit - baggage.length_m
            # max evita piccoli arretramenti dovuti agli arrotondamenti del gap.
            baggage.position_m = max(
                baggage.position_m,
                min(baggage.position_m + distance, max_position),
            )
            front_limit = baggage.position_m - self.config.min_gap_m

    def _evaluate_transfers(self) -> tuple[Baggage, ...]:
        """Seleziona l'uscita senza mutare lo stato osservato dopo il movimento.

        Nel percorso minimo solo il bagaglio più a valle può uscire. Il limite
        usa la stessa sottrazione del movimento, evitando confronti incoerenti
        per arrotondamento. Nessun epsilon anticipa l'uscita.
        """
        if not self.conveyor.baggage:
            return ()
        baggage = self.conveyor.baggage[-1]
        if baggage.position_m >= self.conveyor.config.length_m - baggage.length_m:
            return (baggage,)
        return ()

    def _apply_transfers(self, outgoing: tuple[Baggage, ...]) -> None:
        """Applica una sola volta il risultato della valutazione del tick.

        L'uscita scarica automaticamente. Non si ripete il movimento dopo il
        trasferimento: chi segue sfrutta lo spazio liberato dal prossimo tick.
        Anche un nuovo ammesso a fine nastro attende il tick successivo.
        """
        self.exited_this_tick = outgoing
        for baggage in outgoing:
            if baggage.entered_at_s is None:
                raise ValueError("Un bagaglio in uscita deve essere stato ammesso")
            self.conveyor.baggage.pop()
            baggage.conveyor_id = None
            baggage.exited_at_s = self.time_s
            if baggage.destination_id == self.config.output_id:
                self.correctly_delivered_count += 1
            else:
                self.misdelivered_count += 1
            self._total_travel_time_s += self.time_s - baggage.entered_at_s

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
