import pytest
from robot_agent_brain.planning.layout_constraints import (
    validate_explicit_spacing, validate_explicit_layout_constraints,
)
from test_layout_transaction import setup, original_layout_session


@pytest.mark.parametrize("phrase", ["中心间距20厘米", "中心间距为200毫米", "中心间距0.2米",
                                   "中心间距二十厘米",
                                   "中心间距固定为20厘米", "中心间距固定是20厘米",
                                   "center spacing is fixed at 20 cm", "center spacing is 20 cm",
                                   "center-to-center spacing: 20 cm"])
def test_explicit_center_distance_cannot_be_lost(phrase):
    _, spec, _ = setup(.2)
    validate_explicit_spacing(phrase, spec)
    for spacing in ({"mode": "auto", "auto": True}, {"mode": "center", "value_m": .1}):
        wrong = spec.model_copy(update={"spacing": spec.spacing.model_validate(spacing)})
        with pytest.raises(ValueError, match="explicit_spacing_mismatch"):
            validate_explicit_spacing(phrase, wrong)


@pytest.mark.parametrize("phrase", ["边缘间距固定为20厘米", "边缘间距二十厘米",
                                   "edge-to-edge spacing is fixed at 200 mm"])
def test_explicit_edge_gap_cannot_turn_into_center_distance(phrase):
    _, spec, _ = setup(.2)
    spec = spec.model_copy(update={"spacing": spec.spacing.model_copy(update={"mode": "edge"})})
    validate_explicit_spacing(phrase, spec)
    for wrong in ({"mode": "center", "value_m": .2}, {"mode": "auto", "auto": True},
                  {"mode": "edge", "value_m": .1}):
        with pytest.raises(ValueError, match="explicit_spacing_mismatch"):
            validate_explicit_spacing(phrase, spec.model_copy(
                update={"spacing": spec.spacing.model_validate(wrong)}))


def test_unsupported_numeric_notation_is_not_silently_ignored():
    _, spec, _ = setup(.2)
    with pytest.raises(ValueError, match="number_unsupported"):
        validate_explicit_spacing("中心间距二十三四厘米", spec)


@pytest.mark.parametrize("phrase", ["中心间距20厘米", "中心间距固定为20厘米",
                                   "边缘间距固定为20厘米"])
def test_mismatch_does_not_publish_or_reserve_ids(tmp_path, phrase):
    session, turn = original_layout_session(tmp_path)
    turn = turn.model_copy(update={"instruction": "新增六个苹果，" + phrase,
        "arrangement_spec": turn.arrangement_spec.model_copy(update={"basis": "current"})})
    before = session.scene.raw_document()
    next_id = session.next_scene_object_id
    with pytest.raises(ValueError, match="explicit_spacing_mismatch"):
        session.process_turn("bad", turn)
    assert session.scene.raw_document() == before
    assert session.next_scene_object_id == next_id
    assert session.arrangement_index.snapshot() == []


@pytest.mark.parametrize("pattern,phrase", [
    ({"kind": "circle", "radius_m": .2}, "圆形布局半径固定为20厘米"),
    ({"kind": "circle", "radius_m": .2}, "circle radius is fixed at 200 mm"),
    ({"kind": "ring", "inner_radius_m": .1, "outer_radius_m": .2}, "内半径10厘米，外半径20厘米"),
    ({"kind": "ring", "inner_radius_m": .1, "outer_radius_m": .2}, "inner radius 10 cm, outer radius 20 cm"),
    ({"kind": "arc", "radius_m": .2, "angle_span_deg": 90}, "半径20厘米，圆心角九十度"),
    ({"kind": "arc", "radius_m": .2, "angle_span_deg": 90}, "radius 0.2 m, arc angle 90 degrees"),
])
def test_pattern_dimensions_preserved_without_rewriting(pattern, phrase):
    _, spec, _ = setup()
    spec = spec.model_copy(update={"pattern": spec.pattern.model_validate(pattern)})
    before = spec.model_dump()
    validate_explicit_layout_constraints(phrase, spec)
    assert spec.model_dump() == before
    field = "inner_radius_m" if pattern["kind"] == "ring" else "radius_m"
    altered = spec.model_copy(update={"pattern": spec.pattern.model_copy(update={field: .05})})
    with pytest.raises(ValueError, match="explicit_dimension_mismatch"):
        validate_explicit_layout_constraints(phrase, altered)


@pytest.mark.parametrize("phrase,code", [
    ("半径20厘米", "dimension_mismatch"),
    ("半径固定为20厘米", "dimension_mismatch"),
    ("半径九十三四厘米", "number_unsupported"),
    ("半径90度", "unit_invalid"),
    ("弧角20厘米", "unit_invalid"),
])
def test_explicit_dimension_missing_or_malformed_never_guessed(phrase, code):
    _, spec, _ = setup()
    with pytest.raises(ValueError, match=code):
        validate_explicit_layout_constraints(phrase, spec)


def test_arc_angle_mismatch_is_not_accepted_because_radius_matches():
    _, spec, _ = setup()
    spec = spec.model_copy(update={"pattern": spec.pattern.model_validate(
        {"kind": "arc", "radius_m": .2, "angle_span_deg": 180})})
    with pytest.raises(ValueError, match="pattern.angle_span_deg"):
        validate_explicit_layout_constraints("半径20厘米，弧角90度", spec)


def test_dimension_mismatch_stops_before_allocation(tmp_path):
    session, turn = original_layout_session(tmp_path)
    turn = turn.model_copy(update={"instruction": "新增六个苹果排成圆形，半径固定为20厘米",
        "arrangement_spec": turn.arrangement_spec.model_copy(update={"basis": "current",
            "pattern": turn.arrangement_spec.pattern.model_validate({"kind": "circle", "radius_m": .1})})})
    before, next_id = session.scene.raw_document(), session.next_scene_object_id
    with pytest.raises(ValueError, match="explicit_dimension_mismatch"):
        session.process_turn("wrong-radius", turn)
    assert session.scene.raw_document() == before
    assert session.next_scene_object_id == next_id
    assert session.arrangement_index.snapshot() == []
