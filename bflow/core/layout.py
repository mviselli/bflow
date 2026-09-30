"""Predefined plant: two check-in islands, one sort line with diverts, four outputs.

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
  A1      A2      A3                     island A: desks above, feeding down
  └───────M───────M───────────┐
                              M═════D1════D2════D3════> output-4
  ┌───────M───────M───────────┘     │     │     │
  B1      B2      B3                output-1..3        island B: desks below
```

Belt by belt (← means "fed by"):

```text
merge-a2   ← island-a-1 ← feeder-a1 ← input-a1,   feeder-a2 ← input-a2
merge-a3   ← island-a-2 ← merge-a2,               feeder-a3 ← input-a3
merge-b2   ← island-b-1 ← feeder-b1 ← input-b1,   feeder-b2 ← input-b2
merge-b3   ← island-b-2 ← merge-b2,               feeder-b3 ← input-b3
merge-main ← island-a-3 ← merge-a3,  island-b-4 ← island-b-3 ← merge-b3
merge-main → line-1 → divert-1 → line-2 → divert-2 → line-3 → divert-3 → line-4 → output-4
divert-n   → branch-n → output-n   (n = 1, 2, 3)
```

Each element checks its own values; LayoutConfig then checks that the
elements together form a plant the engine can run (see _check_layout), so an
invalid layout cannot be built.
"""

from collections import Counter, deque
from dataclasses import dataclass
from math import hypot, isfinite

from bflow.core.checks import check_identifier, check_quantity


# Side of the square transfer plate at a merge or sorter, as wide as a belt.
# A belt joining the line from the side ends at the edge of the plate, so a
# bag waiting there stays beside the line; belts along the line reach the
# centre. The engine only uses lengths along the belts: crossing the plate is
# part of the transfer.
JUNCTION_SIZE_M = 1.0


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
        check_identifier("id", self.id)
        check_identifier("label", self.label)
        check_quantity("arrival_rate_bags_s", self.arrival_rate_bags_s)


@dataclass(frozen=True)
class MergeConfig:
    """The point where several belts join one common line, taking turns."""

    id: str
    position: Point

    def __post_init__(self) -> None:
        check_identifier("id", self.id)


@dataclass(frozen=True)
class SorterConfig:
    """The point where each bag is sent onto the branch of its destination."""

    id: str
    position: Point

    def __post_init__(self) -> None:
        check_identifier("id", self.id)


@dataclass(frozen=True)
class OutputConfig:
    """A loading chute: the destination of the bags, shown as a demo flight."""

    id: str
    label: str
    position: Point

    def __post_init__(self) -> None:
        check_identifier("id", self.id)
        check_identifier("label", self.label)


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
        check_identifier("id", self.id)
        check_identifier("source_id", self.source_id)
        check_identifier("target_id", self.target_id)
        check_quantity("speed_m_s", self.speed_m_s, positive=True)
        check_quantity("length_m", self.length_m, positive=True)

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
        check_quantity("baggage_length_m", self.baggage_length_m, positive=True)
        check_quantity("min_gap_m", self.min_gap_m)
        _check_layout(self)


def _check_layout(layout: LayoutConfig) -> None:
    """Raises ValueError at the first rule the plant breaks.

    1. At least one input and one output; identifiers unique among all elements.
    2. A belt comes from an input, merge, sorter or belt and goes to a merge,
       sorter, output or belt, never to itself.
    3. When a belt feeds another belt, both agree: the target's source is it.
    4. An input feeds one belt; a merge joins two or more belts into one; a
       sorter splits one belt into two or more; an output receives one belt.
    5. Connected ends meet on the map: exactly at an input, an output or
       another belt; at a merge or sorter on its centre or up to half a
       junction before it, with the belt pointing at the centre (see
       _meets_junction). A bag fits on every belt.
    6. No cycles: a bag can never come back to where it has been.
    7. Exactly one route from every input to every output: every output is
       reachable, and there are no alternative routes.

    Rules 4 and 6 leave no orphan elements: going back through the sources
    always ends at an input, going forward through the targets at an output.
    """
    nodes = layout.inputs + layout.merges + layout.sorters + layout.outputs
    if not layout.inputs or not layout.outputs:
        raise ValueError("The layout needs at least one input and one output")
    ids = Counter(element.id for element in nodes + layout.belts)
    duplicates = sorted(id for id, count in ids.items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate identifiers: {', '.join(duplicates)}")

    positions = {node.id: node.position for node in nodes}
    belts = {belt.id: belt for belt in layout.belts}
    input_ids = {node.id for node in layout.inputs}
    output_ids = {node.id for node in layout.outputs}
    junction_ids = {node.id for node in layout.merges + layout.sorters}

    for belt in layout.belts:
        if belt.id in (belt.source_id, belt.target_id):
            raise ValueError(f"Belt {belt.id} cannot connect to itself")
        if belt.source_id not in input_ids | junction_ids | belts.keys():
            raise ValueError(f"Belt {belt.id} must come from an input, merge, sorter "
                             f"or belt, not {belt.source_id!r}")
        if belt.target_id not in output_ids | junction_ids | belts.keys():
            raise ValueError(f"Belt {belt.id} must go to a merge, sorter, output "
                             f"or belt, not {belt.target_id!r}")
        if belt.source_id in belts and belts[belt.source_id].target_id != belt.id:
            raise ValueError(f"Belt {belt.id} comes from {belt.source_id}, "
                             f"which does not go to {belt.id}")
        if belt.target_id in belts and belts[belt.target_id].source_id != belt.id:
            raise ValueError(f"Belt {belt.id} goes to {belt.target_id}, "
                             f"which does not come from {belt.id}")

    incoming = Counter(belt.target_id for belt in layout.belts)
    outgoing = Counter(belt.source_id for belt in layout.belts)
    for node in layout.inputs:
        if outgoing[node.id] != 1:
            raise ValueError(f"Input {node.id} must feed exactly one belt, not {outgoing[node.id]}")
    for node in layout.merges:
        if incoming[node.id] < 2 or outgoing[node.id] != 1:
            raise ValueError(f"Merge {node.id} must join two or more belts into one, "
                             f"not {incoming[node.id]} into {outgoing[node.id]}")
    for node in layout.sorters:
        if incoming[node.id] != 1 or outgoing[node.id] < 2:
            raise ValueError(f"Sorter {node.id} must split one belt into two or more, "
                             f"not {incoming[node.id]} into {outgoing[node.id]}")
    for node in layout.outputs:
        if incoming[node.id] != 1:
            raise ValueError(f"Output {node.id} must receive exactly one belt, not {incoming[node.id]}")

    for belt in layout.belts:
        if belt.source_id in junction_ids:
            starts_right = _meets_junction(belt, positions[belt.source_id], at_end=False)
        else:
            source = belts[belt.source_id].end if belt.source_id in belts else positions[belt.source_id]
            starts_right = belt.start == source
        if belt.target_id in junction_ids:
            ends_right = _meets_junction(belt, positions[belt.target_id], at_end=True)
        else:
            target = belts[belt.target_id].start if belt.target_id in belts else positions[belt.target_id]
            ends_right = belt.end == target
        if not starts_right or not ends_right:
            raise ValueError(f"Belt {belt.id} must start where {belt.source_id} is "
                             f"and end where {belt.target_id} is on the map")
        if layout.baggage_length_m > belt.length_m:
            raise ValueError(f"A bag does not fit on belt {belt.id}")

    # The graph of every element: node → belt → belt or node.
    successors: dict[str, list[str]] = {id: [] for id in ids}
    for belt in layout.belts:
        successors[belt.id].append(belt.target_id)
        if belt.source_id not in belts:
            successors[belt.source_id].append(belt.id)
    order = _topological_order(successors)

    # Number of routes from each element to each output, computed from the
    # outputs backwards: an element has the routes of its successors combined.
    routes: dict[str, Counter[str]] = {}
    for id in reversed(order):
        routes[id] = Counter({id: 1}) if id in output_ids else Counter()
        for successor in successors[id]:
            routes[id] += routes[successor]
    for node in layout.inputs:
        for output_id in sorted(output_ids):
            count = routes[node.id][output_id]
            if count == 0:
                raise ValueError(f"Output {output_id} cannot be reached from input {node.id}")
            if count > 1:
                raise ValueError(f"There are {count} routes from input {node.id} to output "
                                 f"{output_id}; alternative routes are not supported")


def _meets_junction(belt: BeltConfig, centre: Point, *, at_end: bool) -> bool:
    """True if a belt's end touches the plate of a merge or sorter centred at ``centre``.

    The end must be on the centre, or on the belt's own line up to half a
    junction before it: an incoming belt stops short of the centre, an
    outgoing one starts after it. The tiny margins absorb rounding.
    """
    end = belt.end if at_end else belt.start
    # Unit vector along the belt, turned to point from the end towards the centre.
    sign = 1 if at_end else -1
    ux = sign * (belt.end.x_m - belt.start.x_m) / belt.length_m
    uy = sign * (belt.end.y_m - belt.start.y_m) / belt.length_m
    dx, dy = centre.x_m - end.x_m, centre.y_m - end.y_m
    ahead = dx * ux + dy * uy        # distance from the end to the centre, along the belt
    aside = abs(dx * uy - dy * ux)   # distance of the centre from the belt's line
    return aside <= 1e-9 and -1e-9 <= ahead <= JUNCTION_SIZE_M / 2 + 1e-9


def _topological_order(successors: dict[str, list[str]]) -> list[str]:
    """Orders the elements so that each comes before its successors (Kahn's algorithm).

    Elements with no predecessors are removed first, then those whose
    predecessors have all been removed, and so on. Elements that are never
    removed lie on a cycle, or after one.
    """
    predecessor_count = Counter(id for targets in successors.values() for id in targets)
    ready = deque(id for id in successors if predecessor_count[id] == 0)
    order = []
    while ready:
        id = ready.popleft()
        order.append(id)
        for successor in successors[id]:
            predecessor_count[successor] -= 1
            if predecessor_count[successor] == 0:
                ready.append(successor)
    if len(order) < len(successors):
        stuck = sorted(set(successors) - set(order))
        raise ValueError(f"The layout has a cycle; on it or after it: {', '.join(stuck)}")
    return order


def default_layout() -> LayoutConfig:
    """The demo plant of the diagram above: two check-in islands, one sort line.

    Every belt is horizontal or vertical, so lengths are exact. Desks feed
    their island collector from the side and stop at the edge of the merge's
    plate; the collectors and the sort line pass through the centres. Each
    desk generates 0.15 bags/s: together 0.9 bags/s, below the 1.25 bags/s
    that a 1 m/s line can carry with 0.6 m bags and a 0.2 m gap.
    """
    rate = 0.15
    edge = JUNCTION_SIZE_M / 2
    return LayoutConfig(
        inputs=(
            InputConfig("input-a1", "A1", Point(2, 0), rate),
            InputConfig("input-a2", "A2", Point(6, 0), rate),
            InputConfig("input-a3", "A3", Point(10, 0), rate),
            InputConfig("input-b1", "B1", Point(2, 12), rate),
            InputConfig("input-b2", "B2", Point(6, 12), rate),
            InputConfig("input-b3", "B3", Point(10, 12), rate),
        ),
        merges=(
            MergeConfig("merge-a2", Point(6, 4)),
            MergeConfig("merge-a3", Point(10, 4)),
            MergeConfig("merge-b2", Point(6, 8)),
            MergeConfig("merge-b3", Point(10, 8)),
            MergeConfig("merge-main", Point(16, 4)),
        ),
        sorters=(
            SorterConfig("divert-1", Point(22, 4)),
            SorterConfig("divert-2", Point(27, 4)),
            SorterConfig("divert-3", Point(32, 4)),
        ),
        outputs=(
            OutputConfig("output-1", "BF 101", Point(22, 9)),
            OutputConfig("output-2", "BF 205", Point(27, 9)),
            OutputConfig("output-3", "BF 312", Point(32, 9)),
            OutputConfig("output-4", "BF 418", Point(37, 4)),
        ),
        belts=(
            # Island A: desks above, feeding down into the collector.
            BeltConfig("feeder-a1", "input-a1", "island-a-1", Point(2, 0), Point(2, 4)),
            BeltConfig("island-a-1", "feeder-a1", "merge-a2", Point(2, 4), Point(6, 4)),
            BeltConfig("feeder-a2", "input-a2", "merge-a2", Point(6, 0), Point(6, 4 - edge)),
            BeltConfig("island-a-2", "merge-a2", "merge-a3", Point(6, 4), Point(10, 4)),
            BeltConfig("feeder-a3", "input-a3", "merge-a3", Point(10, 0), Point(10, 4 - edge)),
            BeltConfig("island-a-3", "merge-a3", "merge-main", Point(10, 4), Point(16, 4)),
            # Island B: desks below, feeding up; its collector joins the line from below.
            BeltConfig("feeder-b1", "input-b1", "island-b-1", Point(2, 12), Point(2, 8)),
            BeltConfig("island-b-1", "feeder-b1", "merge-b2", Point(2, 8), Point(6, 8)),
            BeltConfig("feeder-b2", "input-b2", "merge-b2", Point(6, 12), Point(6, 8 + edge)),
            BeltConfig("island-b-2", "merge-b2", "merge-b3", Point(6, 8), Point(10, 8)),
            BeltConfig("feeder-b3", "input-b3", "merge-b3", Point(10, 12), Point(10, 8 + edge)),
            BeltConfig("island-b-3", "merge-b3", "island-b-4", Point(10, 8), Point(16, 8)),
            BeltConfig("island-b-4", "island-b-3", "merge-main", Point(16, 8), Point(16, 4 + edge)),
            # The sort line, with a branch down to a chute at each divert.
            BeltConfig("line-1", "merge-main", "divert-1", Point(16, 4), Point(22, 4)),
            BeltConfig("branch-1", "divert-1", "output-1", Point(22, 4 + edge), Point(22, 9)),
            BeltConfig("line-2", "divert-1", "divert-2", Point(22, 4), Point(27, 4)),
            BeltConfig("branch-2", "divert-2", "output-2", Point(27, 4 + edge), Point(27, 9)),
            BeltConfig("line-3", "divert-2", "divert-3", Point(27, 4), Point(32, 4)),
            BeltConfig("branch-3", "divert-3", "output-3", Point(32, 4 + edge), Point(32, 9)),
            BeltConfig("line-4", "divert-3", "output-4", Point(32, 4), Point(37, 4)),
        ),
    )


def minimal_layout(*, length_m: float = 10.0, speed_m_s: float = 1.0,
                   arrival_rate_bags_s: float = 0.5, baggage_length_m: float = 0.6,
                   min_gap_m: float = 0.2) -> LayoutConfig:
    """The smallest plant: input-a → belt-1 → output-1, on one straight belt.

    Every bag is destined for output-1. The parameters make it easy to test
    movement, spacing and exits on a single belt.
    """
    end = Point(length_m, 0)
    return LayoutConfig(
        inputs=(InputConfig("input-a", "A", Point(0, 0), arrival_rate_bags_s),),
        merges=(),
        sorters=(),
        outputs=(OutputConfig("output-1", "BF 101", end),),
        belts=(BeltConfig("belt-1", "input-a", "output-1", Point(0, 0), end, speed_m_s),),
        baggage_length_m=baggage_length_m,
        min_gap_m=min_gap_m,
    )
