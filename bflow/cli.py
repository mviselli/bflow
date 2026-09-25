"""Esecuzione senza GUI del percorso predefinito, con riepilogo finale.

    uv run python -m bflow.cli --duration 600 --seed 42

Usa lo stesso motore del server e avanza alla massima velocità, senza
attendere il tempo reale. Restituisce 1 se la conservazione dei bagagli fallisce.
"""

import argparse

from bflow.core.engine import STEP_MS, Engine
from bflow.core.stats import Stats


def _duration_ticks(value: str) -> int:
    """Converte i secondi simulati in tick interi da 50 ms."""
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("la durata deve essere un numero") from None
    if not seconds >= 0 or seconds == float("inf"):
        raise argparse.ArgumentTypeError("la durata deve essere finita e non negativa")
    exact = seconds * 1000 / STEP_MS
    ticks = round(exact)
    if abs(exact - ticks) > 1e-9:
        raise argparse.ArgumentTypeError(f"la durata deve essere un multiplo di {STEP_MS} ms")
    return ticks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bflow.cli",
        description="Esegue BaggageFlow senza interfaccia grafica e stampa un riepilogo.",
    )
    parser.add_argument("--duration", type=_duration_ticks, default=_duration_ticks("600"),
                        metavar="SECONDI", help="durata in secondi simulati (predefinita: 600)")
    parser.add_argument("--seed", type=int, default=42,
                        help="seed del generatore casuale (predefinito: 42)")
    return parser


def format_summary(stats: Stats, seed: int) -> str:
    mean = "—" if stats.mean_travel_time_s is None else f"{stats.mean_travel_time_s:.2f} s"
    conservation = "OK" if stats.is_conserved else "VIOLATA"
    rows = [
        ("Generati", stats.generated),
        ("In attesa all'ingresso", stats.waiting),
        ("Entrati", stats.admitted),
        ("Consegnati correttamente", stats.correctly_delivered),
        ("Usciti nella destinazione sbagliata", stats.misdelivered),
        ("In transito", stats.in_transit),
        ("Tempo medio di percorrenza", mean),
        ("Errori", stats.errors),
        ("Warning", stats.warnings),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [
        "BaggageFlow — riepilogo della run",
        f"Seed {seed} · {stats.time_s:.2f} s simulati ({stats.tick} tick)",
        "",
        *(f"{label + ':':<{width + 1}} {value}" for label, value in rows),
        "",
        f"Conservazione: {conservation} — entrati {stats.admitted} = consegnati "
        f"{stats.correctly_delivered} + errati {stats.misdelivered} + in transito "
        f"{stats.in_transit}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = Engine(seed=args.seed)
    for _ in range(args.duration):
        engine.step()
    stats = engine.stats()
    print(format_summary(stats, args.seed))
    return 0 if stats.is_conserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
