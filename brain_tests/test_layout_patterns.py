import pytest

from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.planning.layout_planner import plan_arrangement


def make_spec(kind, count, **pattern):
    seed = pattern.pop("seed", None)
    return ArrangementSpec(
        arrangement_id="arr-pattern",
        pattern={"kind": kind, **pattern},
        items={"mode": "single", "assets": [{"alias": "apple"}],
               "requested_count": count, "count_mode": "exact"},
        region={"surface_ref": "table", "side": "center"},
        spacing={"mode": "center", "value_m": 0.05}, seed=seed,
    )


@pytest.mark.parametrize("kind", ["line", "grid", "circle", "ring", "arc", "checker", "alternating"])
def test_registered_patterns_are_deterministic(kind):
    kwargs = {}
    if kind == "grid":
        kwargs.update(rows=2, cols=2)
    if kind in {"circle", "arc"}:
        kwargs["radius_m"] = .1
    if kind == "ring":
        kwargs["inner_radius_m"] = .05
        kwargs["outer_radius_m"] = .1
    if kind == "arc":
        kwargs["angle_span_deg"] = 180
    first = plan_arrangement(make_spec(kind, 4, **kwargs))
    second = plan_arrangement(make_spec(kind, 4, **kwargs))
    assert first.model_dump() == second.model_dump()
    assert len(first.slots) == 4
    assert all(0 <= slot.u <= 1 and 0 <= slot.v <= 1 for slot in first.slots)


def test_scatter_uses_seed_for_replay():
    base = make_spec("scatter", 5, seed=12)
    assert plan_arrangement(base).model_dump() == plan_arrangement(base).model_dump()


@pytest.mark.parametrize("count", [1, 2, 5, 6, 7, 10])
def test_grid_count_only_preserves_count_and_wire_round_trip(count):
    from robot_agent_brain.models.understanding_wire import encode, decode
    spec = make_spec("grid", count)
    value = {"protocol_version": "task_understanding.v3.1", "status": "accepted",
             "turn_kind": "scene_layout", "arrangement_spec": spec.model_dump(mode="json")}
    decoded = ArrangementSpec.model_validate(decode(encode(value))["arrangement_spec"])
    plan = plan_arrangement(decoded)
    assert len(plan.slots) == count
    assert len({(s.u, s.v) for s in plan.slots}) == count
    assert plan == plan_arrangement(spec)
    assert decoded.pattern.rows is None and decoded.pattern.cols is None


def test_custom_path_is_normalized_and_count_checked():
    spec = make_spec("custom", 2, path=[(.1, .2), (.9, .8)], description="custom")
    result = plan_arrangement(spec)
    assert [(slot.u, slot.v) for slot in result.slots] == [(.1, .2), (.9, .8)]


def test_single_count_is_shared_by_planner_and_resolver():
    from robot_agent_brain.planning.layout_planner import expanded_aliases
    from robot_agent_brain.scene.layout_resolver import LayoutResolver
    spec = make_spec("line", 6)
    plan = plan_arrangement(spec)
    result = LayoutResolver().resolve(spec, plan, scene_id=1, scene_version=2,
                                      instance_ids=list(range(10, 16)))
    assert expanded_aliases(spec) == ["apple"] * 6
    assert list(result.slot_assets.values()) == ["apple"] * 6


def test_exact_sequence_cannot_silently_shrink_requested_count():
    data = make_spec("line", 6).model_dump()
    data["items"].update(mode="sequence", sequence=["apple", "banana"],
                         assets=[{"alias": "apple"}, {"alias": "banana"}])
    with pytest.raises(ValueError, match="scene_layout_count_conflict"):
        plan_arrangement(ArrangementSpec.model_validate(data))


def test_alternating_sequence_cycles_to_requested_count():
    from robot_agent_brain.planning.layout_planner import expanded_aliases
    data = make_spec("alternating", 6).model_dump()
    data["items"].update(mode="sequence", sequence=["apple", "banana"],
                         assets=[{"alias": "apple"}, {"alias": "banana"}])
    spec = ArrangementSpec.model_validate(data)
    assert expanded_aliases(spec) == ["apple", "banana"] * 3
    assert len(plan_arrangement(spec).slots) == 6


@pytest.mark.parametrize("dimensions,expected", [({"rows": 1}, (6, 1)), ({"cols": 1}, (1, 6))])
def test_partial_grid_dimensions_are_preserved(dimensions, expected):
    plan = plan_arrangement(make_spec("grid", 6, **dimensions))
    assert (len({s.u for s in plan.slots}), len({s.v for s in plan.slots})) == expected


def test_column_major_orders_slots_down_columns():
    plan = plan_arrangement(make_spec("grid", 6, rows=2, cols=3, order="column_major"))
    assert [(s.u, s.v) for s in plan.slots][:3] == [(0, 0), (0, 1), (.5, 0)]


def test_custom_duplicate_positions_rejected():
    with pytest.raises(ValueError, match="duplicate_slot_position"):
        plan_arrangement(make_spec("custom", 2, path=[(.5, .5), (.5, .5)]))


def test_clockwise_circle_changes_order_and_tangent():
    data = make_spec("circle", 4, radius_m=.2, order="clockwise").model_dump()
    data["orientation"] = {"mode": "follow_pattern"}
    plan = plan_arrangement(ArrangementSpec.model_validate(data))
    assert plan.slots[1].v == pytest.approx(.05)
    assert plan.orientation_hints[0] == pytest.approx(-90)


def test_full_arc_does_not_duplicate_endpoint():
    plan = plan_arrangement(make_spec("arc", 4, radius_m=.2, angle_span_deg=360))
    points = {(round(s.u, 8), round(s.v, 8)) for s in plan.slots}
    assert len(points) == 4


def test_single_arc_slot_uses_arc_midpoint():
    plan = plan_arrangement(make_spec("arc", 1, radius_m=.2, angle_span_deg=180))
    assert (plan.slots[0].u, plan.slots[0].v) == pytest.approx((.95, .5))


def test_generated_scatter_seed_can_replay_exact_slots():
    spec = make_spec("scatter", 5)
    first = plan_arrangement(spec)
    assert first.effective_seed is not None
    assert spec.seed is None
    replay = plan_arrangement(spec.model_copy(update={"seed": first.effective_seed}))
    assert replay.slots == first.slots
    assert plan_arrangement(spec).effective_seed == first.effective_seed


def test_scatter_explicit_seed_preserved():
    assert plan_arrangement(make_spec("scatter", 5, seed=123)).effective_seed == 123


@pytest.mark.parametrize("order", ["row_major", "column_major"])
def test_checker_assets_alternate_in_both_dimensions(order):
    from robot_agent_brain.planning.layout_planner import expanded_aliases
    data = make_spec("checker", 8, rows=2, cols=4, order=order).model_dump()
    data["items"].update(mode="sequence", sequence=["apple", "banana"],
                         assets=[{"alias": "apple"}, {"alias": "banana"}])
    spec = ArrangementSpec.model_validate(data)
    slots = plan_arrangement(spec).slots
    assignment = {(round(s.u * 3), round(s.v)): alias
                  for s, alias in zip(slots, expanded_aliases(spec))}
    for (col, row), alias in assignment.items():
        if (col + 1, row) in assignment:
            assert alias != assignment[col + 1, row]
        if (col, row + 1) in assignment:
            assert alias != assignment[col, row + 1]
