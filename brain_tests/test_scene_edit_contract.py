import json
import pytest
from pydantic import ValidationError

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan
from robot_agent_brain.models.task_understanding import TaskParseOutput
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from test_query_scene_continuity import supported_scene


@pytest.mark.parametrize("contract", [BrainTurn, TaskParseOutput])
def test_legacy_direct_edit_payload_is_rejected(contract):
    with pytest.raises(ValidationError):
        contract.model_validate(dict(status="accepted", turn_kind="scene_edit", instruction="增加一个香蕉",
            scene_edit=dict(operation="add", semantic_name="banana", category="fruit", count=1)))


@pytest.mark.parametrize("old_field,value", [("semantic_name","apple"), ("category","fruit"), ("count",2)])
def test_operation_cannot_select_objects_via_legacy_fields(old_field, value):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SceneEditIntent.model_validate(dict(operation="add", target="apple") | {old_field:value})


def test_operation_requires_target_and_editor_rejects_standalone_operation():
    with pytest.raises(ValidationError):
        SceneEditIntent(operation="add")
    editor = SceneEditor(BrainConfig().load_assets())
    with pytest.raises(ValueError, match="scene_edit_plan_required"):
        editor.edit_result(SceneEditIntent(operation="add", target="apple"), supported_scene())


@pytest.mark.parametrize("target,reference", [("unknown","apple"), ("apple","unknown")])
def test_edit_plan_rejects_unknown_entity_references(target, reference):
    with pytest.raises(ValidationError, match="scene_edit_unknown"):
        SceneEditPlan(entities=[dict(entity_id="apple", semantic_name="apple", category="fruit")],
            operations=[SceneEditIntent(operation="move_relative", target=target, reference=reference, relation="right_of")])


def test_all_scene_edit_prompt_examples_are_canonical():
    edits = []
    for line in TASK_UNDERSTANDING_PROMPT.splitlines():
        if line.startswith('{"status"'):
            value = json.loads(line)
            if value.get("turn_kind") == "scene_edit":
                parsed = TaskParseOutput.model_validate(value)
                assert isinstance(parsed.scene_edit, SceneEditPlan)
                assert all(op.target for op in parsed.scene_edit.operations)
                edits.append(parsed.scene_edit)
    assert len(edits) >= 2
    assert any(p.operations[0].reference is None for p in edits)


def test_relative_add_reference_uses_catalog_alias_without_instance_aliases():
    scene = supported_scene()
    scene.objects.pop()  # only table and apple
    scene.objects[1].properties = {}
    before = scene.model_dump()
    plan = SceneEditPlan(entities=[
        dict(entity_id="new", semantic_name="香蕉", category="fruit"),
        dict(entity_id="reference", semantic_name="苹果", category="fruit")],
        operations=[SceneEditIntent(operation="add", target="new", reference="reference", relation="right_of")])
    result = SceneEditor(BrainConfig().load_assets()).edit_result(plan, scene)
    final = SceneManager(scene).apply_patch(result.patch)
    assert result.created_object_ids == ["banana_01"]
    assert final.objects[-1].semantic_name == "banana"
    assert final.objects[-1].transform.position[0] > scene.objects[1].transform.position[0]
    assert final.objects[-1].properties["support"] == "table_01"
    assert final.scene_version == scene.scene_version + 1
    assert scene.model_dump() == before
