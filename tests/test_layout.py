"""Predefined plant: elements, connections, map coordinates and lengths."""

from dataclasses import FrozenInstanceError

import pytest

from bflow.core.layout import (
    BeltConfig, InputConfig, LayoutConfig, MergeConfig, OutputConfig, Point,
    SorterConfig, default_layout,
)


def _positions(layout):
    nodes = layout.inputs + layout.merges + layout.sorters + layout.outputs
    return {node.id: node.position for node in nodes}


def _follow(layout, belt_id):
    """Belt ids from belt_id to the next node, and that node's id."""
    belts = {belt.id: belt for belt in layout.belts}
    path = [belt_id]
    target = belts[belt_id].target_id
    while target in belts:
        path.append(target)
        target = belts[target].target_id
    return path, target


def test_default_layout_has_three_inputs_a_merge_a_sorter_and_three_outputs():
    layout = default_layout()
    assert [node.id for node in layout.inputs] == ["input-a", "input-b", "input-c"]
    assert [node.id for node in layout.merges] == ["merge"]
    assert [node.id for node in layout.sorters] == ["sorter"]
    assert [node.id for node in layout.outputs] == ["output-1", "output-2", "output-3"]
    ids = [element.id for element in
           layout.inputs + layout.merges + layout.sorters + layout.outputs + layout.belts]
    assert len(ids) == len(set(ids))


def test_every_input_reaches_the_merge_and_the_common_line_reaches_the_sorter():
    layout = default_layout()
    first_belts = {belt.source_id: belt.id for belt in layout.belts}
    assert _follow(layout, first_belts["input-a"]) == (["feeder-a-1", "feeder-a-2"], "merge")
    assert _follow(layout, first_belts["input-b"]) == (["feeder-b"], "merge")
    assert _follow(layout, first_belts["input-c"]) == (["feeder-c-1", "feeder-c-2"], "merge")
    assert _follow(layout, first_belts["merge"]) == (["collector"], "sorter")


def test_each_sorter_branch_ends_at_a_different_output():
    layout = default_layout()
    branches = [belt.id for belt in layout.belts if belt.source_id == "sorter"]
    assert [_follow(layout, belt_id) for belt_id in branches] == [
        (["branch-1-1", "branch-1-2"], "output-1"),
        (["branch-2"], "output-2"),
        (["branch-3-1", "branch-3-2"], "output-3"),
    ]


def test_connected_ends_meet_on_the_map():
    layout = default_layout()
    positions = _positions(layout)
    belts = {belt.id: belt for belt in layout.belts}
    for belt in layout.belts:
        source = belts[belt.source_id].end if belt.source_id in belts else positions[belt.source_id]
        target = belts[belt.target_id].start if belt.target_id in belts else positions[belt.target_id]
        assert belt.start == source, belt.id
        assert belt.end == target, belt.id


def test_belt_lengths_are_the_exact_map_distances():
    lengths = {belt.id: belt.length_m for belt in default_layout().belts}
    assert lengths == {
        "feeder-a-1": 8, "feeder-a-2": 4, "feeder-b": 8, "feeder-c-1": 8, "feeder-c-2": 4,
        "collector": 12,
        "branch-1-1": 4, "branch-1-2": 8, "branch-2": 8, "branch-3-1": 4, "branch-3-2": 8,
    }
    diagonal = BeltConfig("belt", "a", "b", Point(1, 1), Point(4, 5))
    assert diagonal.length_m == 5


def test_default_rates_are_below_the_capacity_of_the_common_line():
    layout = default_layout()
    collector = next(belt for belt in layout.belts if belt.id == "collector")
    capacity = collector.speed_m_s / (layout.baggage_length_m + layout.min_gap_m)
    demand = sum(node.arrival_rate_bags_s for node in layout.inputs)
    assert demand == 0.75
    assert demand < capacity == 1.25


def test_layout_is_immutable():
    layout = default_layout()
    with pytest.raises(FrozenInstanceError):
        layout.min_gap_m = 1
    with pytest.raises(FrozenInstanceError):
        layout.belts[0].speed_m_s = 2
    with pytest.raises(FrozenInstanceError):
        layout.inputs[0].position.x_m = 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_map_coordinates_must_be_finite(value):
    with pytest.raises(ValueError, match="finite"):
        Point(value, 0)
    with pytest.raises(ValueError, match="finite"):
        Point(0, value)


@pytest.mark.parametrize("fields", [
    {"id": ""}, {"source_id": " "}, {"target_id": ""},
    {"speed_m_s": 0}, {"speed_m_s": -1}, {"speed_m_s": float("nan")},
    {"end": Point(0, 0)},
])
def test_invalid_belt(fields):
    values = dict(id="belt", source_id="a", target_id="b", start=Point(0, 0), end=Point(2, 0))
    with pytest.raises(ValueError):
        BeltConfig(**(values | fields))


@pytest.mark.parametrize("make", [
    lambda: InputConfig("", "A", Point(0, 0), 1),
    lambda: InputConfig("input", "", Point(0, 0), 1),
    lambda: InputConfig("input", "A", Point(0, 0), -0.1),
    lambda: InputConfig("input", "A", Point(0, 0), float("inf")),
    lambda: MergeConfig(" ", Point(0, 0)),
    lambda: SorterConfig("", Point(0, 0)),
    lambda: OutputConfig("output", " ", Point(0, 0)),
    lambda: LayoutConfig((), (), (), (), (), baggage_length_m=0),
    lambda: LayoutConfig((), (), (), (), (), min_gap_m=-0.1),
])
def test_invalid_elements(make):
    with pytest.raises(ValueError):
        make()


def test_a_zero_rate_and_no_gap_are_allowed():
    assert InputConfig("input", "A", Point(0, 0), 0).arrival_rate_bags_s == 0
    assert LayoutConfig((), (), (), (), (), min_gap_m=0).min_gap_m == 0
