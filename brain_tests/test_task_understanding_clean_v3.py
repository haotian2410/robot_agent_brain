"""Contract tests for the single clean task-understanding v3 wire."""

import pytest
from pydantic import ValidationError

from robot_agent_brain.errors import BrainError
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
from robot_agent_brain.models.task_understanding import (
    SceneEditWire,
    SceneQueryWire,
    TaskParseWireOutput,
    parse_qwen_turn,
    task_understanding_v3_wire_schema,
)


def envelope(**payload):
    value = {
        "protocol_version": "task_understanding.v3",
        "status": "accepted",
        "turn_kind": "scene_edit",
        "arm_usage": "unspecified",
        "hold_constraints": [],
        "clarification_question": None,
        "scene_edit": None,
        "scene_query": None,
        "session_control": None,
        "robot_setup_request": None,
        "entities": [],
        "operations": [],
        "relations": [],
    }
    value.update(payload)
    return value


def test_runtime_prompt_is_single_clean_v3_source():
    assert "task_understanding_clean_v3" not in TASK_UNDERSTANDING_PROMPT
    assert "VISION_GROUNDING_PROMPT" not in TASK_UNDERSTANDING_PROMPT
    assert "SKILL_PLANNING_PROMPT" not in TASK_UNDERSTANDING_PROMPT
    assert "Atomic Skill 规划器" not in TASK_UNDERSTANDING_PROMPT
    assert "route_selection.txt" not in TASK_UNDERSTANDING_PROMPT
    assert "lexicon" not in TASK_UNDERSTANDING_PROMPT.casefold()
    assert "task_understanding.v3" in TASK_UNDERSTANDING_PROMPT


def test_runtime_prompt_binds_vague_scene_motion_to_python_scale_policy():
    assert "motion_scale=small" in TASK_UNDERSTANDING_PROMPT
    assert "一点/稍微/轻微/一下" in TASK_UNDERSTANDING_PROMPT
    assert "机器人任务仍不能凭空猜测执行距离" in TASK_UNDERSTANDING_PROMPT


def test_runtime_prompt_uses_python_default_for_unspecified_asset_style():
    assert "不要因为目录存在多个" in TASK_UNDERSTANDING_PROMPT
    assert "Python 会按配置的默认资产完成选择" in TASK_UNDERSTANDING_PROMPT
    assert "operation=add" in TASK_UNDERSTANDING_PROMPT


def test_v3_schema_requires_route_and_all_payload_slots():
    schema = task_understanding_v3_wire_schema()
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["$defs"]["SceneEditWire"]["required"]) == {
        "scene_basis", "entities", "relations", "operations"
    }
    assert set(schema["$defs"]["SceneQueryWire"]["required"]) == {
        "query_type", "entities", "relations", "target", "reference",
        "predicate", "evidence_source"
    }


def test_scene_payloads_are_structured_wire_models():
    scene_edit = {
        "scene_basis": "current",
        "entities": [{"id": "apple", "name": "apple", "category": "fruit"}],
        "relations": [],
        "operations": [{"operation": "add", "target": "apple", "relation": None, "reference": None}],
    }
    scene_query = {
        "query_type": "neighbors",
        "entities": [{"entity_id": "basket", "semantic_name": "basket", "category": "container"}],
        "relations": [], "target": "basket", "reference": None,
        "predicate": None, "evidence_source": "scene",
    }
    edit_wire = TaskParseWireOutput.model_validate(envelope(scene_edit=scene_edit))
    query_wire = TaskParseWireOutput.model_validate(envelope(turn_kind="scene_query", scene_edit=None, scene_query=scene_query))
    assert isinstance(edit_wire.scene_edit, SceneEditWire)
    assert isinstance(query_wire.scene_query, SceneQueryWire)
    assert edit_wire.scene_edit.entities[0].entity_id == "apple"
    assert query_wire.scene_query.target == "basket"


def test_robot_payload_uses_canonical_v3_entity_and_operation_fields():
    payload = envelope(
        turn_kind="robot_task", scene_edit=None,
        entities=[
            {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
            {"entity_id": "basket", "semantic_name": "basket", "category": "container"},
        ],
        operations=[{
            "operation": "pick_and_place", "source": "apple", "destination": "basket",
            "placement_target": {"kind": "container_interior", "reference": "basket", "relation": "inside"},
        }],
    )
    turn = parse_qwen_turn(payload, "把苹果放进篮子")
    assert turn.task_intent is not None
    assert turn.task_intent.entities[0].entity_id == "apple"
    assert turn.task_intent.operations[0].task_type.value == "pick_and_place"
    schema = task_understanding_v3_wire_schema()
    operation = schema["$defs"]["RobotOperationWire"]
    assert "operation" in operation["required"] and "type" not in operation["properties"]


def test_robot_semantic_validation_error_keeps_actual_operation_path():
    payload = envelope(
        turn_kind="robot_task", scene_edit=None,
        entities=[{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        operations=[{"operation": "grasp"}],
    )
    with pytest.raises(BrainError) as error:
        parse_qwen_turn(payload, "抓取苹果")
    assert error.value.issue.code == "semantic_protocol_error"
    assert error.value.issue.path == "operations.0"


def test_query_registered_table_reference_is_allowed_but_unknown_is_not():
    query = {
        "query_type": "relation",
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        "relations": [], "target": "apple", "reference": "table", "predicate": "left_of",
        "evidence_source": "scene",
    }
    turn = parse_qwen_turn(envelope(turn_kind="scene_query", scene_edit=None, scene_query=query),
                           "苹果在桌子左边吗？")
    assert turn.scene_query.reference == "table"
    with pytest.raises(BrainError, match="query_reference_missing"):
        parse_qwen_turn(envelope(turn_kind="scene_query", scene_edit=None,
                                 scene_query={**query, "reference": "window"}), "苹果在窗户左边吗？")


def test_scene_edit_table_reference_is_resolved_later_not_declared_entity():
    turn = parse_qwen_turn(envelope(scene_edit={
        "scene_basis": "current",
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        "relations": [],
        "operations": [{"operation": "add", "target": "apple", "relation": "on", "reference": "table"}],
    }), "在桌面上增加一个苹果")
    assert turn.scene_edit is not None
    assert [entity.entity_id for entity in turn.scene_edit.entities] == ["apple"]
    assert turn.scene_edit.scene_refs[0].canonical_value == "table"


def test_corner_add_is_normalized_to_on_region_before_scene_edit_validation():
    value = envelope(scene_edit={
        "scene_basis": "current",
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        "relations": [],
        # This is the shape emitted by older constrained decoders for a
        # corner phrase.  It is safe to normalize because the instruction
        # explicitly names a table corner and supplies no distance.
        "operations": [{"operation": "add", "target": "apple", "direction": "left"}],
    })
    turn = parse_qwen_turn(value, "在桌子左上角增加一个苹果")
    operation = turn.scene_edit.operations[0]
    assert operation.relation.value == "on"
    assert operation.reference == "table"
    assert operation.placement_region == "left_front"
    assert operation.placement_hint == "any"
    assert operation.direction is None


def test_object_relative_add_without_reference_is_clarification_not_table_guess():
    value = envelope(protocol_version="task_understanding.v3.1", scene_edit={
        "scene_basis": "current",
        "entities": [
            {"entity_id": "banana", "semantic_name": "banana", "category": "fruit"},
            {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
        ],
        "relations": [],
        "operations": [{"operation": "add", "target": "banana", "relation": "right_of",
                         "reference": None}],
    })
    turn = parse_qwen_turn(value, "在苹果右侧增加一个香蕉")
    assert turn.status.value == "clarification_required"
    assert "参照物" in (turn.clarification_question or "")
    assert "苹果" in (turn.clarification_question or "")


@pytest.mark.parametrize(("instruction", "region"), [
    ("在桌面左前角增加一个苹果", "left_front"),
    ("在桌面右前角增加一个苹果", "right_front"),
    ("在桌面左后角增加一个苹果", "left_back"),
    ("在桌面右后角增加一个苹果", "right_back"),
])
def test_explicit_front_back_corner_aliases_keep_both_axes(instruction, region):
    value = envelope(scene_edit={
        "scene_basis": "current",
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        "relations": [],
        "operations": [{"operation": "add", "target": "apple", "relation": "on", "reference": "table"}],
    })
    turn = parse_qwen_turn(value, instruction)
    assert turn.scene_edit.operations[0].placement_region == region


def test_table_side_without_surface_context_is_clarification_even_if_qwen_says_on():
    value = envelope(scene_edit={
        "scene_basis": "current",
        "entities": [{"entity_id": "baseball", "semantic_name": "baseball", "category": "ball"}],
        "relations": [],
        "operations": [{"operation": "add", "target": "baseball", "relation": "on", "reference": "table"}],
    })
    turn = parse_qwen_turn(value, "在桌子左侧增加一个棒球")
    assert turn.status.value == "clarification_required"
    assert "桌面左侧" in turn.clarification_question
    assert "右边" not in turn.clarification_question


def test_tabletop_side_is_not_rejected_as_external_ambiguity():
    value = envelope(scene_edit={
        "scene_basis": "current",
        "entities": [{"entity_id": "baseball", "semantic_name": "baseball", "category": "ball"}],
        "relations": [],
        "operations": [{"operation": "add", "target": "baseball", "relation": "on", "reference": "table",
                         "placement_region": "left_half"}],
    })
    turn = parse_qwen_turn(value, "在桌面左侧增加一个棒球")
    assert turn.status.value == "accepted"


def test_scene_edit_target_and_replacement_must_be_declared_entities():
    with pytest.raises(ValidationError, match="scene_edit_unknown_selector"):
        TaskParseWireOutput.model_validate(envelope(scene_edit={
            "scene_basis": "current",
            "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "relations": [],
            "operations": [{"operation": "add", "target": "missing", "relation": None, "reference": None}],
        }))
    with pytest.raises(ValidationError, match="scene_replace_unknown_entity"):
        TaskParseWireOutput.model_validate(envelope(scene_edit={
            "scene_basis": "current",
            "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "relations": [],
            "operations": [{"operation": "replace", "target": "apple", "replacement_entity": "banana",
                             "relation": None, "reference": None}],
        }))


def test_binary_scene_relation_requires_reference():
    with pytest.raises(ValidationError, match="paired"):
        TaskParseWireOutput.model_validate(envelope(scene_edit={
            "scene_basis": "current",
            "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "relations": [],
            "operations": [{"operation": "add", "target": "apple", "relation": "near", "reference": None}],
        }))


def test_invalid_query_target_is_semantic_error_and_missing_near_is_clarification():
    query = {
        "query_type": "neighbors",
        "entities": [{"entity_id": "basket", "semantic_name": "basket", "category": "container"}],
        "relations": [{"scope": "selection", "subject": "basket", "relation": "near", "reference": None}],
        "target": "basket", "reference": None, "predicate": None, "evidence_source": "scene",
    }
    turn = parse_qwen_turn(envelope(turn_kind="scene_query", scene_edit=None, scene_query=query), "篮子旁边有什么")
    assert turn.status.value == "clarification_required"
    with pytest.raises(BrainError, match="semantic_protocol_error"):
        parse_qwen_turn(envelope(turn_kind="scene_query", scene_edit=None, scene_query={**query, "relations": [], "target": "missing"}), "查询不存在")


def test_selection_root_relation_is_canonicalized_into_scene_query():
    """Constrained decoders sometimes put the selector on the envelope."""
    query = {
        "query_type": "selection",
        "entities": [
            {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
            {"entity_id": "basket", "semantic_name": "basket", "category": "container"},
        ],
        "relations": [], "target": "apple", "reference": None,
        "predicate": None, "evidence_source": "scene",
    }
    value = envelope(turn_kind="scene_query", scene_edit=None, scene_query=query,
                     relations=[{"subject": "apple", "relation": "nearest", "reference": "basket"}])
    turn = parse_qwen_turn(value, "哪个苹果离篮子最近")
    assert turn.scene_query is not None
    assert turn.scene_query.relations[0].relation.value == "nearest"
    assert turn.scene_query.relations[0].reference == "basket"


def test_selection_root_entities_are_canonicalized_into_scene_query():
    query = {
        "query_type": "selection", "entities": [], "relations": [], "target": "apple",
        "reference": None, "predicate": None, "evidence_source": "scene",
    }
    value = envelope(turn_kind="scene_query", scene_edit=None, scene_query=query,
                     entities=[
                         {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
                         {"entity_id": "basket", "semantic_name": "basket", "category": "container"},
                     ], relations=[{"subject": "apple", "relation": "nearest", "reference": "basket"}])
    turn = parse_qwen_turn(value, "哪个苹果离篮子最近")
    assert [item.entity_id for item in turn.scene_query.entities] == ["apple", "basket"]


def test_missing_farthest_reference_is_a_clarification_for_scene_edit():
    value = envelope(scene_edit={
        "scene_basis": "current",
        "entities": [{"entity_id": "banana", "semantic_name": "banana", "category": "fruit"}],
        "relations": [{"scope": "selection", "subject": "banana", "relation": "farthest", "reference": None}],
        "operations": [{"operation": "translate", "target": "banana", "direction": "left",
                         "distance_m": 0.05, "relation": None, "reference": None}],
    })
    turn = parse_qwen_turn(value, "把最远的香蕉向左移动五厘米")
    assert turn.status.value == "clarification_required"
    assert "参照物" in (turn.clarification_question or "")


def test_replace_schema_error_points_at_replacement_entity():
    value = envelope(scene_edit={
        "scene_basis": "current",
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        "relations": [],
        "operations": [{"operation": "replace", "target": "apple", "relation": None, "reference": None}],
    })
    with pytest.raises(BrainError) as error:
        parse_qwen_turn(value, "把苹果替换成香蕉")
    assert error.value.issue.code == "provider_output_schema_invalid"
    assert error.value.issue.category == "provider_schema"
    assert error.value.issue.path.endswith("replacement_entity")


def test_replace_wire_preserves_declared_replacement_entity():
    value = envelope(scene_edit={
        "scene_basis": "current",
        "entities": [
            {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
            {"entity_id": "banana", "semantic_name": "banana", "category": "fruit"},
        ],
        "relations": [],
        "operations": [{"operation": "replace", "target": "apple",
                         "replacement_entity": "banana", "relation": None, "reference": None}],
    })
    turn = parse_qwen_turn(value, "把苹果替换成香蕉")
    assert turn.scene_edit is not None
    assert turn.scene_edit.operations[0].replacement_entity == "banana"
