"""Headless run of the default route, with a final summary.

    uv run python -m bflow.cli --duration 600 --seed 42

Uses the same engine as the server and steps as fast as possible, without
waiting for real time. Exits with status 1 if baggage conservation fails.
"""

import argparse

from bflow.core.engine import STEP_MS, Engine
from bflow.core.stats import Stats


def _duration_ticks(value: str) -> int:
    """Converts simulated seconds into whole 50 ms ticks."""
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("duration must be a number") from None
    if not seconds >= 0 or seconds == float("inf"):
        raise argparse.ArgumentTypeError("duration must be finite and non-negative")
    exact = seconds * 1000 / STEP_MS
    ticks = round(exact)
    if abs(exact - ticks) > 1e-9:
        raise argparse.ArgumentTypeError(f"duration must be a multiple of {STEP_MS} ms")
    return ticks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bflow.cli",
        description="Runs BaggageFlow without the graphical interface and prints a summary.",
    )
    parser.add_argument("--duration", type=_duration_ticks, default=_duration_ticks("600"),
                        metavar="SECONDS", help="duration in simulated seconds (default: 600)")
    parser.add_argument("--seed", type=int, default=42,
                        help="random generator seed (default: 42)")
    return parser


def format_summary(stats: Stats, seed: int) -> str:
    mean = "—" if stats.mean_travel_time_s is None else f"{stats.mean_travel_time_s:.2f} s"
    conservation = "OK" if stats.is_conserved else "FAILED"
    rows = [
        ("Generated", stats.generated),
        ("Waiting at entrance", stats.waiting),
        ("Admitted", stats.admitted),
        ("Correctly delivered", stats.correctly_delivered),
        ("Misdelivered", stats.misdelivered),
        ("In transit", stats.in_transit),
        ("Mean travel time", mean),
        ("Errors", stats.errors),
        ("Warnings", stats.warnings),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [
        "BaggageFlow — run summary",
        f"Seed {seed} · {stats.time_s:.2f} simulated s ({stats.tick} ticks)",
        "",
        *(f"{label + ':':<{width + 1}} {value}" for label, value in rows),
        "",
        f"Conservation: {conservation} — admitted {stats.admitted} = delivered "
        f"{stats.correctly_delivered} + misdelivered {stats.misdelivered} + in transit "
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
