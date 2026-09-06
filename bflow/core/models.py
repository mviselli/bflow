"""Dati del motore, senza dipendenze da server o grafica.

Le distanze sono in metri e i timestamp in secondi simulati, mai tempo reale.
La posizione indica il bordo posteriore del bagaglio: sul nastro occupa
``[position_m, position_m + length_m]``. L'ammissione avviene a posizione zero;
il bordo anteriore raggiunge il termine a ``length_m`` del nastro.

Le configurazioni sono immutabili; bagagli e contenuto dei nastri sono stato
mutabile. I controlli alla costruzione non sostituiscono quelli che il motore
dovrà applicare durante movimento, ammissione e trasferimenti.
"""

from dataclasses import dataclass, field
from math import isfinite


def _identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} deve essere un identificativo non vuoto")


def _quantity(name: str, value: float, *, positive: bool = False) -> None:
    if not isfinite(value) or value < 0 or (positive and value == 0):
        bound = "positivo" if positive else "non negativo"
        raise ValueError(f"{name} deve essere finito e {bound}")


@dataclass
class Baggage:
    """Bagaglio in attesa, ammesso oppure uscito.

    ``destination_id`` è l'uscita prevista e non cambia con lo smistamento.
    Prima dell'ammissione ``conveyor_id`` e ``entered_at_s`` sono None.
    Dopo l'uscita ``conveyor_id`` torna None e ``exited_at_s`` è valorizzato;
    ``position_m`` conserva l'ultima posizione. Il tempo di percorrenza parte
    da ``entered_at_s``, escludendo l'attesa all'ingresso.
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
        _identifier("id", self.id)
        _identifier("destination_id", self.destination_id)
        _quantity("length_m", self.length_m, positive=True)
        _quantity("position_m", self.position_m)
        _quantity("generated_at_s", self.generated_at_s)
        if self.conveyor_id is not None:
            _identifier("conveyor_id", self.conveyor_id)
        if self.entered_at_s is None:
            if self.conveyor_id is not None or self.exited_at_s is not None:
                raise ValueError("Un bagaglio non ammesso non può essere sul nastro o uscito")
            if self.position_m != 0:
                raise ValueError("Un bagaglio in attesa deve avere posizione zero")
        else:
            _quantity("entered_at_s", self.entered_at_s)
            if self.entered_at_s < self.generated_at_s:
                raise ValueError("L'ammissione non può precedere la generazione")
            if self.exited_at_s is None:
                if self.conveyor_id is None:
                    raise ValueError("Un bagaglio in transito deve avere un nastro")
            else:
                _quantity("exited_at_s", self.exited_at_s)
                if self.exited_at_s < self.entered_at_s:
                    raise ValueError("L'uscita non può precedere l'ammissione")
                if self.conveyor_id is not None:
                    raise ValueError("Un bagaglio uscito non può essere su un nastro")


@dataclass(frozen=True)
class ConveyorConfig:
    """Parametri fisici di un nastro; velocità nominale strettamente positiva."""

    id: str = "belt-1"
    length_m: float = 10.0
    speed_m_s: float = 1.0

    def __post_init__(self) -> None:
        _identifier("id", self.id)
        _quantity("length_m", self.length_m, positive=True)
        _quantity("speed_m_s", self.speed_m_s, positive=True)


@dataclass
class Conveyor:
    """Stato del nastro, con bagagli ordinati dall'ingresso verso l'uscita.

    Il motore manterrà ordine, appartenenza e distanziamento della lista.
    La configurazione rimane separata dallo stato per consentire il reset.
    """

    config: ConveyorConfig
    baggage: list[Baggage] = field(default_factory=list)


@dataclass(frozen=True)
class SimulationConfig:
    """Percorso minimo: input_id → conveyor.id → output_id.

    Ogni bagaglio ha destinazione output_id. Un ritmo nullo disabilita la
    generazione; min_gap_m è lo spazio libero fra due bagagli, oltre l'ingombro.
    La topologia completa e la geometria grafica saranno definite nel layout.
    """

    input_id: str = "input-a"
    output_id: str = "output-1"
    conveyor: ConveyorConfig = field(default_factory=ConveyorConfig)
    arrival_rate_bags_s: float = 0.5
    baggage_length_m: float = 0.6
    min_gap_m: float = 0.2

    def __post_init__(self) -> None:
        _identifier("input_id", self.input_id)
        _identifier("output_id", self.output_id)
        if len({self.input_id, self.conveyor.id, self.output_id}) != 3:
            raise ValueError("Ingresso, nastro e uscita devono avere identificativi distinti")
        _quantity("arrival_rate_bags_s", self.arrival_rate_bags_s)
        _quantity("baggage_length_m", self.baggage_length_m, positive=True)
        _quantity("min_gap_m", self.min_gap_m)
        if self.baggage_length_m > self.conveyor.length_m:
            raise ValueError("Il bagaglio deve poter essere contenuto nel nastro")
