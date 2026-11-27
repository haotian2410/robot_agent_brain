import pytest

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.scene.user_feedback import explain_issue


@pytest.mark.parametrize("code", ["scene_layout_collision", "scene_layout_capacity_exceeded",
                                 "scene_layout_workspace_exceeded"])
def test_layout_geometry_refusal_is_not_a_model_protocol_error(code):
    issue = BrainApplication._issue(ValueError(code), "processing")
    assert issue.code == code
    assert issue.category == "geometry_layout"
    assert issue.stage == "processing"
    assert not issue.retryable


@pytest.mark.parametrize("code,category", [
    ("scene_layout_count_conflict", "semantic_protocol"),
    ("scene_layout_region_unresolved", "semantic_protocol"),
    ("provider_output_schema_invalid", "provider_output_schema"),
    ("asset_choice_missing", "provider_output_schema"),
])
def test_layout_classification_does_not_swallow_protocol_or_asset_choice_errors(code, category):
    assert BrainApplication._issue(ValueError(code), "processing").category == category


@pytest.mark.parametrize("code, explanation", [
    ("scene_layout_collision", "碰撞"),
    ("scene_layout_workspace_exceeded", "工作区"),
    ("scene_layout_capacity_exceeded", "无法容纳"),
])
def test_layout_geometry_feedback_preserves_specific_cause(code, explanation):
    error = ValueError(code)
    issue = BrainApplication._issue(error, "processing")
    explain_issue(issue, error, None, None)
    assert explanation in issue.message
    assert "场景未改变" in issue.message
    assert issue.code == code
    assert issue.category == "geometry_layout"


@pytest.mark.parametrize("code", ["scene_layout_explicit_spacing_mismatch",
                                 "scene_layout_explicit_dimension_mismatch",
                                 "scene_layout_explicit_dimension_unit_invalid"])
def test_explicit_parameter_loss_is_not_reported_as_collision(code):
    error = ValueError(code + ": pattern.radius_m")
    issue = BrainApplication._issue(error, "processing")
    explain_issue(issue, error, None, None)
    assert "未完整保留" in issue.message
    assert "场景未改变" in issue.message
    assert issue.category == "semantic_protocol"
    assert issue.code == code
