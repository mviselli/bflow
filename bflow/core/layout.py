"""Predefined plant: three inputs, a merge, a common line, a sorter, three outputs.

The plant is a graph. Inputs, merges, sorters and outputs are the nodes;
belts are the edges and carry bags from their source to their target. A
target can also be another belt: a line that turns a corner is drawn as two
straight belts, one after the other, reusing the same belt logic.

Map coordinates are in metres, with x to the right and y downwards, as on the
screen. This is the explicit conversion between map and engine: a belt is a
straight segment from ``start`` to ``end``, and its length along which bags
move is exactly the distance between the two points. The page only scales
metres to pixels.

```text
input-a ─ feeder-a-1 ─┐                    ┌─ branch-1-2 ─ output-1
                  feeder-a-2          branch-1-1
input-b ─ feeder-b ─ merge ─ collector ─ sorter ─ branch-2 ─ output-2
                  feeder-c-2          branch-3-1
input-c ─ feeder-c-1 ─┘                    └─ branch-3-2 ─ output-3
```

This module only describes the plant; each element checks its own values.
Checks across elements (unique identifiers, connections, reachability,
cycles) are separate from the data.
"""

from dataclasses import dataclass
from math import hypot, isfinite

from bflow.core.models import _identifier, _quantity


@dataclass(frozen=True)
class Point:
    """A point on the map, in metres; y grows downwards."""

    x_m: float
    y_m: float

    def __post_init__(self) -> None:
        if not isfinite(self.x_m) or not isfinite(self.y_m):
            raise ValueError("Map coordinates must be finite")


@dataclass(frozen=True)
class InputConfig:
    """A check-in desk that generates bags at a configurable rate.

    A zero rate disables generation. ``label`` is the desk letter shown on
    the map.
    """

    id: str
    label: str
    position: Point
    arrival_rate_bags_s: float

    def __post_init__(self) -> None:
        _identifier("id", self.id)
        _identifier("label", self.label)
        _quantity("arrival_rate_bags_s", self.arrival_rate_bags_s)


@dataclass(frozen=True)
class MergeConfig:
    """The point where several belts join one common line, taking turns."""

    id: str
    position: Point

    def __post_init__(self) -> None:
        _identifier("id", self.id)


@dataclass(frozen=True)
class SorterConfig:
    """The point where each bag is sent onto the branch of its destination."""

    id: str
    position: Point

    def __post_init__(self) -> None:
        _identifier("id", self.id)


@dataclass(frozen=True)
class OutputConfig:
    """A loading chute: the destination of the bags, shown as a demo flight."""

    id: str
    label: str
    position: Point

    def __post_init__(self) -> None:
        _identifier("id", self.id)
        _identifier("label", self.label)


@dataclass(frozen=True)
class BeltConfig:
    """A straight belt from ``start`` to ``end``, carrying bags from source to target.

    ``source_id`` and ``target_id`` are the ids of a node or of another belt.
    Position 0 along the belt is at ``start`` and ``length_m`` at ``end``.
    """

    id: str
    source_id: str
    target_id: str
    start: Point
    end: Point
    speed_m_s: float = 1.0

    def __post_init__(self) -> None:
        _identifier("id", self.id)
        _identifier("source_id", self.source_id)
        _identifier("target_id", self.target_id)
        _quantity("speed_m_s", self.speed_m_s, positive=True)
        _quantity("length_m", self.length_m, positive=True)

    @property
    def length_m(self) -> float:
        """Distance between the two ends: the same length on the map and in the engine."""
        return hypot(self.end.x_m - self.start.x_m, self.end.y_m - self.start.y_m)


@dataclass(frozen=True)
class LayoutConfig:
    """The whole plant, plus the bag size and spacing shared by every belt.

    ``min_gap_m`` is the free space between two bags, beyond their length.
    """

    inputs: tuple[InputConfig, ...]
    merges: tuple[MergeConfig, ...]
    sorters: tuple[SorterConfig, ...]
    outputs: tuple[OutputConfig, ...]
    belts: tuple[BeltConfig, ...]
    baggage_length_m: float = 0.6
    min_gap_m: float = 0.2

    def __post_init__(self) -> None:
        _quantity("baggage_length_m", self.baggage_length_m, positive=True)
        _quantity("min_gap_m", self.min_gap_m)


def default_layout() -> LayoutConfig:
    """The demo plant of the diagram above.

    Every belt is horizontal or vertical, so lengths are exact. Each input
    generates 0.25 bags/s: together 0.75 bags/s, below the 1.25 bags/s that a
    1 m/s line can carry with 0.6 m bags and a 0.2 m gap.
    """
    rate = 0.25
    return LayoutConfig(
        inputs=(
            InputConfig("input-a", "A", Point(0, 0), rate),
            InputConfig("input-b", "B", Point(0, 4), rate),
            InputConfig("input-c", "C", Point(0, 8), rate),
        ),
        merges=(MergeConfig("merge", Point(8, 4)),),
        sorters=(SorterConfig("sorter", Point(20, 4)),),
        outputs=(
            OutputConfig("output-1", "BF 101", Point(28, 0)),
            OutputConfig("output-2", "BF 205", Point(28, 4)),
            OutputConfig("output-3", "BF 312", Point(28, 8)),
        ),
        belts=(
            BeltConfig("feeder-a-1", "input-a", "feeder-a-2", Point(0, 0), Point(8, 0)),
            BeltConfig("feeder-a-2", "feeder-a-1", "merge", Point(8, 0), Point(8, 4)),
            BeltConfig("feeder-b", "input-b", "merge", Point(0, 4), Point(8, 4)),
            BeltConfig("feeder-c-1", "input-c", "feeder-c-2", Point(0, 8), Point(8, 8)),
            BeltConfig("feeder-c-2", "feeder-c-1", "merge", Point(8, 8), Point(8, 4)),
            BeltConfig("collector", "merge", "sorter", Point(8, 4), Point(20, 4)),
            BeltConfig("branch-1-1", "sorter", "branch-1-2", Point(20, 4), Point(20, 0)),
            BeltConfig("branch-1-2", "branch-1-1", "output-1", Point(20, 0), Point(28, 0)),
            BeltConfig("branch-2", "sorter", "output-2", Point(20, 4), Point(28, 4)),
            BeltConfig("branch-3-1", "sorter", "branch-3-2", Point(20, 4), Point(20, 8)),
            BeltConfig("branch-3-2", "branch-3-1", "output-3", Point(20, 8), Point(28, 8)),
        ),
    )
