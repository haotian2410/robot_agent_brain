import pytest

from robot_agent_brain.contracts.arrangement import ArrangementPattern


@pytest.mark.parametrize("points", [
    [(0, 0), (1, 1), (0, 1), (1, 0)],
    [(0, 0), (1, 0), (.5, 0)],
    [(0, 0), (1, 0), (1, 1), (.5, 0)],
])
def test_crossing_backtracking_and_nonadjacent_touch_rejected(points):
    with pytest.raises(ValueError, match="scene_layout_path_self_intersection"):
        ArrangementPattern(kind="custom", path=points)


@pytest.mark.parametrize("points", [
    [(0, 0), (.5, 0), (1, 0)],
    [(0, 0), (1, 0), (1, 1), (0, 1)],
    [(.5, .5)],
])
def test_simple_path_allowed(points):
    assert ArrangementPattern(kind="custom", path=points).path == points


def test_equal_arclength_uses_segment_length_not_vertex_index():
    from robot_agent_brain.planning.layout_path_sampler import sample_polyline
    path = [(0, 0), (.25, 0), (.25, .75)]
    assert sample_polyline(path, 5) == [(0, 0), (.25, 0), (.25, .25), (.25, .5), (.25, .75)]
    assert path == [(0, 0), (.25, 0), (.25, .75)]


def test_single_slot_is_at_path_midpoint():
    from robot_agent_brain.planning.layout_path_sampler import sample_polyline
    assert sample_polyline([(0, 0), (1, 0)], 1) == [(.5, 0)]
    assert sample_polyline([(.2, .3)], 1) == [(.2, .3)]
    with pytest.raises(ValueError, match="path_degenerate"):
        sample_polyline([(.2, .3)], 2)


@pytest.mark.parametrize("count", [0, -1, 1001, True])
def test_path_count_is_bounded(count):
    from robot_agent_brain.planning.layout_path_sampler import sample_polyline
    with pytest.raises(ValueError, match="count_conflict"):
        sample_polyline([(0, 0), (1, 0)], count)


def test_custom_path_can_sample_more_objects_than_vertices():
    from test_layout_patterns import make_spec
    from robot_agent_brain.planning.layout_planner import plan_arrangement
    spec = make_spec("custom", 5, path=[(.1, .5), (.9, .5)])
    first = plan_arrangement(spec)
    assert first == plan_arrangement(spec)
    assert len(first.slots) == 5
    assert [slot.u for slot in first.slots] == pytest.approx([.1, .3, .5, .7, .9])
    assert first.planner_source == "deterministic"
