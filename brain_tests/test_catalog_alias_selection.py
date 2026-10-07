import pytest

from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject
from robot_agent_brain.contracts.task_intent import TaskEntity, TaskIntent, Operation
from robot_agent_brain.contracts.turn import BrainTurn, SceneQueryIntent, SceneEditIntent, SceneEditPlan
from robot_agent_brain.pipeline import BrainPipeline


@pytest.fixture
def uploaded(tmp_path):
    assets = BrainConfig().load_assets()
    path = tmp_path / "scene.json"
    payload = SceneConfig(scene_id="uploaded", objects=[SceneObject(
        scene_object_id="apple_01", asset_id="demo_apple", semantic_name="apple", category="fruit", properties={})]).model_dump_json()
    path.write_text(payload, encoding="utf-8")
    scene = SceneFileCodec(assets).load(path)
    assert scene.objects[0].properties == {}
    before = scene.model_dump()
    yield BrainPipeline(None, assets), scene
    assert scene.model_dump() == before
    assert path.read_text(encoding="utf-8") == payload


def entity(name):
    return TaskEntity(entity_id="target", semantic_name=name, category="fruit")


def query_turn(name):
    return BrainTurn(status="accepted", turn_kind="scene_query", instruction="count",
        scene_query=SceneQueryIntent(query_type="count", entities=[entity(name)], target="target"))


def grasp_turn(name):
    return BrainTurn(status="accepted", turn_kind="robot_task", instruction="抓住苹果",
        task_intent=TaskIntent(instruction="抓住苹果", entities=[entity(name)],
            operations=[Operation(operation_id="op-1", task_type="grasp", target="target")]))


def test_uploaded_scene_query_uses_catalog_alias_without_instance_alias(uploaded):
    pipeline, scene = uploaded
    result = pipeline.process_turn("query", query_turn("苹果"), scene)
    assert result.scene_query_result.count == 1
    assert result.scene_query_result.object_ids == ["apple_01"]


@pytest.mark.parametrize("overrides", [None, {"target": ["apple_01"]}])
def test_uploaded_scene_robot_grounding_uses_catalog_alias(uploaded, overrides):
    pipeline, scene = uploaded
    result = pipeline.process_turn("grasp", grasp_turn("苹果"), scene, bindings_override=overrides)
    assert result.grounded_task.entities[0].scene_object_ids == ["apple_01"]
    assert result.commands is not None


def test_undeclared_alias_never_falls_back_to_same_category(uploaded):
    pipeline, scene = uploaded
    assert pipeline.process_turn("query", query_turn("梨子"), scene).scene_query_result.count == 0
    with pytest.raises(ValueError, match="grounding_missing"):
        pipeline.process_turn("grasp", grasp_turn("梨子"), scene)
    with pytest.raises(ValueError, match="grounding_binding_invalid"):
        pipeline.process_turn("grasp", grasp_turn("梨子"), scene, bindings_override={"target":["apple_01"]})


def test_scene_edit_receives_catalog_aliases_too(uploaded):
    pipeline, scene = uploaded
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="苹果右移五厘米",
        scene_edit=SceneEditPlan(entities=[entity("苹果")], operations=[SceneEditIntent(
            operation="translate", target="target", direction="right", distance_m=.05)]))
    result = pipeline.process_turn("edit", turn, scene)
    operation = result.scene_patch.operations[0]
    assert operation.scene_object_id == "apple_01"
    assert operation.transform.position == (.05, 0, 0)


def test_object_name_is_canonicalized_and_instance_alias_is_retained(uploaded):
    pipeline, original = uploaded
    scene = original.model_copy(deep=True)
    scene.objects[0].semantic_name = "苹果"
    scene.objects[0].properties = {"aliases": ["我的点心"]}
    for name in ("apple", "我的点心"):
        result = pipeline.process_turn(name, query_turn(name), scene)
        assert result.scene_query_result.object_ids == ["apple_01"]
    assert scene.objects[0].properties == {"aliases": ["我的点心"]}
