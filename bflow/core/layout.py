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

Each element checks its own values; LayoutConfig then checks that the
elements together form a plant the engine can run (see _check_layout), so an
invalid layout cannot be built.
"""

from collections import Counter, deque
from dataclasses import dataclass
from math import hypot, isfinite

from bflow.core.checks import check_identifier, check_quantity


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
    5. Connected ends meet on the map, and a bag fits on every belt.
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
        source = belts[belt.source_id].end if belt.source_id in belts else positions[belt.source_id]
        target = belts[belt.target_id].start if belt.target_id in belts else positions[belt.target_id]
        if belt.start != source or belt.end != target:
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
