"""Headless run of the plant, with a final summary.

    uv run python -m bflow.cli --duration 600 --seed 42
    uv run python -m bflow.cli --layout minimal   # the one-belt route of the page

Uses the same engine as the server and steps as fast as possible, without
waiting for real time. Exits with status 1 if baggage conservation fails.
"""

import argparse

from bflow.core.engine import STEP_MS, Engine
from bflow.core.layout import default_layout, minimal_layout
from bflow.core.stats import Stats


LAYOUTS = {"full": default_layout, "minimal": minimal_layout}


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
    parser.add_argument("--layout", choices=LAYOUTS, default="full",
                        help="full: six desks in two islands, one sort line, four outputs; "
                             "minimal: one belt (default: full)")
    return parser


def format_summary(stats: Stats, seed: int, layout_name: str = "full") -> str:
    """The totals, then one line per input, output and belt, as the engine counted them."""
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
        ("Throughput (60 s)", stats.throughput),
        ("Errors", stats.errors),
        ("Warnings", stats.warnings),
    ]
    width = max(len(label) for label, _ in rows)
    id_width = max(len(item_id) for item_id in
                   [node.input_id for node in stats.inputs]
                   + [node.output_id for node in stats.outputs]
                   + [belt.belt_id for belt in stats.belts])
    lines = [
        "BaggageFlow — run summary",
        f"Layout {layout_name} · seed {seed} · {stats.time_s:.2f} simulated s "
        f"({stats.tick} ticks)",
        "",
        *(f"{label + ':':<{width + 1}} {value}" for label, value in rows),
        "",
        "Inputs (waiting)",
        *(f"  {node.input_id:<{id_width}} {node.waiting:>5}" for node in stats.inputs),
        "",
        "Outputs (correct, wrong)",
        *(f"  {node.output_id:<{id_width}} {node.correctly_delivered:>5} {node.misdelivered:>5}"
          for node in stats.outputs),
        "",
        "Belts (bags / capacity, occupancy)",
        *(f"  {belt.belt_id:<{id_width}} {belt.bags:>5} / {belt.capacity:<3} "
          f"{belt.occupancy:>4.0%}" for belt in stats.belts),
        "",
        f"Conservation: {conservation} — admitted {stats.admitted} = delivered "
        f"{stats.correctly_delivered} + misdelivered {stats.misdelivered} + in transit "
        f"{stats.in_transit}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = Engine(LAYOUTS[args.layout](), seed=args.seed)
    for _ in range(args.duration):
        engine.step()
    stats = engine.stats()
    print(format_summary(stats, args.seed, args.layout))
    return 0 if stats.is_conserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
