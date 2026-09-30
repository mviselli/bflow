"""Predefined plant: elements, connections, map coordinates and lengths."""

from dataclasses import FrozenInstanceError, replace

import pytest

from bflow.core.layout import (
    BeltConfig, InputConfig, LayoutConfig, MergeConfig, OutputConfig, Point,
    SorterConfig, default_layout, minimal_layout,
)
from tests.layouts import compact_layout


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


def test_default_layout_has_two_islands_of_three_desks_one_line_and_four_outputs():
    layout = default_layout()
    assert [node.id for node in layout.inputs] == [
        "input-a1", "input-a2", "input-a3", "input-b1", "input-b2", "input-b3"]
    assert [node.label for node in layout.inputs] == ["A1", "A2", "A3", "B1", "B2", "B3"]
    assert [node.id for node in layout.merges] == [
        "merge-a2", "merge-a3", "merge-b2", "merge-b3", "merge-main"]
    assert [node.id for node in layout.sorters] == ["divert-1", "divert-2", "divert-3"]
    assert [node.id for node in layout.outputs] == ["output-1", "output-2", "output-3", "output-4"]
    ids = [element.id for element in
           layout.inputs + layout.merges + layout.sorters + layout.outputs + layout.belts]
    assert len(ids) == len(set(ids))


def test_desks_join_their_island_one_after_the_other_and_the_islands_join_the_line():
    layout = default_layout()
    first_belts = {belt.source_id: belt.id for belt in layout.belts}
    for island in "ab":
        assert _follow(layout, first_belts[f"input-{island}1"]) == (
            [f"feeder-{island}1", f"island-{island}-1"], f"merge-{island}2")
        assert _follow(layout, first_belts[f"input-{island}2"]) == (
            [f"feeder-{island}2"], f"merge-{island}2")
        assert _follow(layout, first_belts[f"merge-{island}2"]) == (
            [f"island-{island}-2"], f"merge-{island}3")
        assert _follow(layout, first_belts[f"input-{island}3"]) == (
            [f"feeder-{island}3"], f"merge-{island}3")
    assert _follow(layout, "island-a-3") == (["island-a-3"], "merge-main")
    assert _follow(layout, "island-b-3") == (["island-b-3", "island-b-4"], "merge-main")


def test_the_line_passes_three_diverts_each_with_a_branch_to_one_output():
    layout = default_layout()
    assert [_follow(layout, belt.id) for belt in layout.belts
            if belt.id.startswith("line-")] == [
        (["line-1"], "divert-1"), (["line-2"], "divert-2"),
        (["line-3"], "divert-3"), (["line-4"], "output-4"),
    ]
    for number in "123":
        assert _follow(layout, f"branch-{number}") == ([f"branch-{number}"], f"output-{number}")


def test_side_belts_stop_at_the_edge_of_the_junction_and_the_line_crosses_its_centre():
    layout = default_layout()
    positions = _positions(layout)
    belts = {belt.id: belt for belt in layout.belts}
    junctions = {node.id for node in layout.merges + layout.sorters}
    side = {"feeder-a2", "feeder-a3", "feeder-b2", "feeder-b3", "island-b-4",
            "branch-1", "branch-2", "branch-3"}
    for belt in layout.belts:
        for node_id, point in ((belt.source_id, belt.start), (belt.target_id, belt.end)):
            if node_id in junctions:
                centre = positions[node_id]
                distance = abs(point.x_m - centre.x_m) + abs(point.y_m - centre.y_m)
                assert distance == (0.5 if belt.id in side else 0), belt.id
            elif node_id in belts:
                assert point in (belts[node_id].start, belts[node_id].end), belt.id
            else:
                assert point == positions[node_id], belt.id


def test_belt_lengths_are_the_exact_map_distances():
    lengths = {belt.id: belt.length_m for belt in default_layout().belts}
    assert lengths == {
        "feeder-a1": 4, "island-a-1": 4, "feeder-a2": 3.5, "island-a-2": 4, "feeder-a3": 3.5,
        "island-a-3": 6,
        "feeder-b1": 4, "island-b-1": 4, "feeder-b2": 3.5, "island-b-2": 4, "feeder-b3": 3.5,
        "island-b-3": 6, "island-b-4": 3.5,
        "line-1": 6, "branch-1": 4.5, "line-2": 5, "branch-2": 4.5, "line-3": 5,
        "branch-3": 4.5, "line-4": 5,
    }
    diagonal = BeltConfig("belt", "a", "b", Point(1, 1), Point(4, 5))
    assert diagonal.length_m == 5


def test_default_rates_are_below_the_capacity_of_the_sort_line():
    layout = default_layout()
    line = next(belt for belt in layout.belts if belt.id == "line-1")
    capacity = line.speed_m_s / (layout.baggage_length_m + layout.min_gap_m)
    demand = sum(node.arrival_rate_bags_s for node in layout.inputs)
    assert demand == pytest.approx(0.9)
    assert demand < capacity == 1.25


def test_layout_is_immutable():
    layout = compact_layout()
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
    assert replace(compact_layout(), min_gap_m=0).min_gap_m == 0


# Validation of the plant as a whole. Each case changes the compact layout
# just enough to break one rule.


def _change_belt(layout, belt_id, **changes):
    belts = tuple(replace(belt, **changes) if belt.id == belt_id else belt
                  for belt in layout.belts)
    return replace(layout, belts=belts)


def _add(layout, **elements):
    return replace(layout, **{name: getattr(layout, name) + tuple(added)
                              for name, added in elements.items()})


def _invalid_layouts():
    layout = compact_layout()
    return [
        ("at least one input", lambda: replace(layout, inputs=())),
        ("at least one input and one output", lambda: replace(layout, outputs=())),
        ("Duplicate identifiers: collector",
         lambda: _add(layout, outputs=[OutputConfig("collector", "X", Point(30, 4))])),
        ("must come from an input, merge, sorter or belt, not 'input-x'",
         lambda: _change_belt(layout, "feeder-b", source_id="input-x")),
        ("must come from .* not 'output-1'",
         lambda: _change_belt(layout, "feeder-b", source_id="output-1")),
        ("must go to a merge, sorter, output or belt, not 'input-b'",
         lambda: _change_belt(layout, "feeder-b", target_id="input-b")),
        ("cannot connect to itself",
         lambda: _change_belt(layout, "collector", target_id="collector")),
        ("feeder-a-2 comes from feeder-a-1, which does not go to feeder-a-2",
         lambda: _change_belt(layout, "feeder-a-1", target_id="merge")),
        ("feeder-a-1 goes to feeder-a-2, which does not come from feeder-a-1",
         lambda: _change_belt(layout, "feeder-a-2", source_id="merge")),
        ("Input input-d must feed exactly one belt, not 0",
         lambda: _add(layout, inputs=[InputConfig("input-d", "D", Point(0, 12), 0.25)])),
        ("Merge merge-2 must join two or more belts into one, not 0 into 0",
         lambda: _add(layout, merges=[MergeConfig("merge-2", Point(12, 12))])),
        ("Sorter sorter-2 must split one belt into two or more, not 0 into 0",
         lambda: _add(layout, sorters=[SorterConfig("sorter-2", Point(12, 12))])),
        ("Output output-4 must receive exactly one belt, not 0",
         lambda: _add(layout, outputs=[OutputConfig("output-4", "BF 400", Point(28, 12))])),
        ("Belt collector must start where merge is and end where sorter is",
         lambda: replace(layout, sorters=(SorterConfig("sorter", Point(21, 4)),))),
        ("Belt feeder-b must start where input-b is",
         lambda: _change_belt(layout, "feeder-b", start=Point(1, 4))),
        ("A bag does not fit on belt feeder-a-2",
         lambda: replace(layout, baggage_length_m=5)),
        ("cycle; on it or after it: .*collector.*merge.*sorter",
         lambda: _add(layout, belts=[BeltConfig("return", "sorter", "merge",
                                                Point(20, 4), Point(8, 4))])),
        ("Output output-4 cannot be reached from input input-a",
         lambda: _add(layout,
                      inputs=[InputConfig("input-d", "D", Point(0, 12), 0.25)],
                      outputs=[OutputConfig("output-4", "BF 400", Point(28, 12))],
                      belts=[BeltConfig("direct", "input-d", "output-4",
                                        Point(0, 12), Point(28, 12))])),
        ("There are 2 routes from input input-a to output output-2",
         lambda: replace(
             layout,
             merges=layout.merges + (MergeConfig("merge-2", Point(24, 4)),),
             belts=tuple(belt for belt in layout.belts if belt.id != "branch-2") + (
                 BeltConfig("branch-2", "sorter", "merge-2", Point(20, 4), Point(24, 4)),
                 BeltConfig("branch-2-bis", "sorter", "merge-2", Point(20, 4), Point(24, 4)),
                 BeltConfig("branch-2-out", "merge-2", "output-2", Point(24, 4), Point(28, 4)),
             ))),
    ]


@pytest.mark.parametrize("message, make", _invalid_layouts(),
                         ids=[message for message, _ in _invalid_layouts()])
def test_invalid_layout(message, make):
    with pytest.raises(ValueError, match=message):
        make()


@pytest.mark.parametrize("belt_id, changes, length", [
    ("feeder-b", {"end": Point(7.5, 4)}, 7.5),      # stops at the edge of the merge's plate
    ("feeder-a-2", {"end": Point(8, 3.5)}, 3.5),    # the same, coming from above
    ("branch-2", {"start": Point(20.5, 4)}, 7.5),   # leaves from the edge of the sorter's plate
    ("collector", {"start": Point(8.25, 4), "end": Point(19.75, 4)}, 11.5),
])
def test_a_belt_may_end_at_the_edge_of_a_junction_pointing_at_its_centre(belt_id, changes, length):
    layout = _change_belt(compact_layout(), belt_id, **changes)
    belt = next(belt for belt in layout.belts if belt.id == belt_id)
    assert belt.length_m == length


@pytest.mark.parametrize("belt_id, changes", [
    ("feeder-b", {"end": Point(7.4, 4)}),          # stops short of the plate
    ("feeder-b", {"end": Point(8.5, 4)}),          # runs past the centre
    ("feeder-a-2", {"end": Point(8.2, 3.6)}),      # close enough, but not pointing at the centre
    ("branch-2", {"start": Point(20.6, 4)}),
    ("feeder-b", {"start": Point(0.1, 4)}),        # inputs and outputs have no plate
])
def test_a_belt_away_from_a_junction_or_askew_is_rejected(belt_id, changes):
    with pytest.raises(ValueError, match=f"Belt {belt_id} must start where"):
        _change_belt(compact_layout(), belt_id, **changes)


def test_a_single_belt_from_input_to_output_is_a_valid_plant():
    layout = LayoutConfig(
        inputs=(InputConfig("input-a", "A", Point(0, 0), 0.5),),
        merges=(), sorters=(),
        outputs=(OutputConfig("output-1", "BF 101", Point(10, 0)),),
        belts=(BeltConfig("belt-1", "input-a", "output-1", Point(0, 0), Point(10, 0)),),
    )
    assert layout.belts[0].length_m == 10


def test_a_bag_as_long_as_the_shortest_belt_fits():
    assert replace(compact_layout(), baggage_length_m=4).baggage_length_m == 4


def test_minimal_layout_is_one_belt_from_input_to_output():
    layout = minimal_layout()
    (belt,) = layout.belts
    assert (belt.source_id, belt.id, belt.target_id) == ("input-a", "belt-1", "output-1")
    assert (belt.length_m, belt.speed_m_s) == (10, 1)
    assert layout.inputs[0].arrival_rate_bags_s == 0.5
    assert (layout.baggage_length_m, layout.min_gap_m) == (0.6, 0.2)


@pytest.mark.parametrize("fields", [
    {"length_m": 0}, {"length_m": float("inf")}, {"speed_m_s": 0}, {"speed_m_s": -1},
    {"arrival_rate_bags_s": -1}, {"arrival_rate_bags_s": float("inf")},
    {"min_gap_m": -0.1}, {"baggage_length_m": 0}, {"baggage_length_m": 11},
])
def test_invalid_minimal_layout(fields):
    with pytest.raises(ValueError):
        minimal_layout(**fields)


def test_minimal_layout_allows_no_arrivals_no_gap_and_exact_fit():
    layout = minimal_layout(arrival_rate_bags_s=0, min_gap_m=0, baggage_length_m=10)
    assert layout.baggage_length_m == layout.belts[0].length_m
