"""Plants used only by the tests.

The demo plant (default_layout) has two-way merges and sorters only; the
compact plant keeps the engine's three-way merges and sorters covered, and
its short, fixed ids make the rule tests easy to read.
"""

from bflow.core.layout import (
    BeltConfig, InputConfig, LayoutConfig, MergeConfig, OutputConfig, Point, SorterConfig,
)


def compact_layout() -> LayoutConfig:
    """Three desks meeting at one merge, one collector, one three-way sorter.

    ```text
    input-a ─ feeder-a-1 ─┐                    ┌─ branch-1-2 ─ output-1
                      feeder-a-2          branch-1-1
    input-b ─ feeder-b ─ merge ─ collector ─ sorter ─ branch-2 ─ output-2
                      feeder-c-2          branch-3-1
    input-c ─ feeder-c-1 ─┘                    └─ branch-3-2 ─ output-3
    ```

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
