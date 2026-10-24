import json
from pathlib import Path

import pytest

from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.task_intent import Operation, PlacementTarget, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.contracts.turn import BrainTurn, TurnKind, TurnStatus
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper


ROOT = Path(__file__).parents[1]
FINAL_MODELS_ROOT = ROOT / "model/final_models"

# The raw asset package is intentionally excluded from Git and wheels.  Run
# these integration checks when the deployment asset bundle is installed.
if not FINAL_MODELS_ROOT.exists():
    pytest.skip("final_models asset bundle is not installed", allow_module_level=True)


def final_config():
    return BrainConfig.load(ROOT / "config/final_models.json")


def test_final_models_namespaces_and_duplicate_name_resolution():
    assets = final_config().load_assets()
    assert assets.resolve("$LIBRARY_SERVER/1", "model").semantic_name == "apple"
    assert assets.resolve("$LIBRARY_SERVER/1", "robot").semantic_name == "ur5e_arm"
    assert len(assets.find_by_name("basket")) == 2
    with pytest.raises(ValueError, match="type_required"):
        assets.resolve("$LIBRARY_SERVER/1")


def test_all_final_models_scenes_load_and_roundtrip():
    config = final_config()
    codec = SceneFileCodec(config.load_assets())
    for path in sorted((ROOT / "model/final_models/scenes").glob("*/*.json")):
        scene = codec.load(path)
        assert codec.payload(scene) == json.loads(path.read_text(encoding="utf-8"))


def test_final_models_template_bootstrap_preserves_platform_and_filters_variant():
    config = final_config()
    assets = config.load_assets()
    template = SceneFileCodec(assets).load(config.default_scene)
    settings = config.bootstrap_settings()
    bootstrap = SceneBootstrapper(
        assets, config.load_defaults(), robot=config.robot, table_metadata_ref=settings["default_table_metadata_ref"],
        robot_metadata_ref=settings["default_robot_metadata_ref"], robot_driver=settings["default_robot_driver"],
        template_scene=template,
    )
    intent = TaskIntent(
        instruction="把苹果放进蓝色篮子",
        entities=[
            TaskEntity(entity_id="apple", semantic_name="apple", category="fruit"),
            TaskEntity(entity_id="basket", semantic_name="basket", category="container", color="blue"),
        ],
        operations=[Operation(operation_id="op-1", task_type=TaskType.PICK_AND_PLACE, source="apple",
                              destination="basket", placement_target=PlacementTarget(kind="container_interior", reference="basket"))],
    )
    turn = BrainTurn(status=TurnStatus.ACCEPTED, turn_kind=TurnKind.ROBOT_TASK,
                     instruction=intent.instruction, task_intent=intent)
    result = bootstrap.prepare(turn, scene_id=123)
    assert [obj.object_id_in_scene for obj in result.scene.objects[:7]] == [obj.object_id_in_scene for obj in template.objects]
    assert result.scene.objects[-2].object_name_in_scene == "apple"
    assert result.scene.objects[-1].object_name_in_scene == "basket"
    assert result.scene.objects[-1].components[1].properties == {"path": "$LIBRARY_SERVER/4", "type": "model"}
    from robot_agent_brain.grounding.scene_grounder import SceneGrounder
    grounded = SceneGrounder(assets=assets).ground(intent, result.scene)
    assert grounded.entities[1].metadata_type == "model"


def test_scene_import_missing_or_wrong_type_fails(tmp_path):
    config = final_config()
    codec = SceneFileCodec(config.load_assets())
    raw = json.loads(Path(config.default_scene).read_text(encoding="utf-8"))
    metadata = next(c["properties"] for c in raw["objects"][2]["components"] if c["component_type"] == "MetadataRef")
    del metadata["type"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="type_required"):
        codec.load(path)
    metadata["type"] = "invalid"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="scene_file_invalid"):
        codec.load(path)


def test_attachment_world_pose_is_not_guessed():
    from robot_agent_brain.scene.scene_graph import world_transform
    config = final_config()
    scene = SceneFileCodec(config.load_assets()).load(config.default_scene)
    for obj in scene.objects:
        if any(c.component_type == "RobotAttachment" for c in obj.components):
            with pytest.raises(ValueError, match="requires_platform"):
                world_transform(scene, obj.object_id_in_scene)


def test_uploaded_generic_category_scene_grounds_named_objects():
    from robot_agent_brain.grounding.semantic_entity_selector import discover_candidates
    config = final_config()
    assets = config.load_assets()
    scene = SceneFileCodec(assets).load(FINAL_MODELS_ROOT / "scenes/3/ur5e_table_sorting.json")
    for name, category, identifier in [("apple", "fruit", 7), ("basket", "container", 12)]:
        entity = TaskEntity(entity_id=name, semantic_name=name, category=category)
        assert [o.object_id_in_scene for o in discover_candidates(entity, scene, assets=assets)] == [identifier]
    scene = SceneFileCodec(assets).load(FINAL_MODELS_ROOT / "scenes/4/ur5e_table_cabinet.json")
    for name, identifier in [("table", 1), ("cabinet", 9)]:
        entity = TaskEntity(entity_id=name, semantic_name=name, category="furniture")
        assert [o.object_id_in_scene for o in discover_candidates(
            entity, scene, aliases=config.load_semantic_aliases(), assets=assets)] == [identifier]


def test_scene_edit_add_preserves_template_and_typed_reference():
    from robot_agent_brain.contracts.turn import SceneEditPlan, SceneEditIntent
    from robot_agent_brain.scene.editor import SceneEditor
    from robot_agent_brain.scene.scene_manager import SceneManager
    config = final_config()
    assets = config.load_assets()
    scene = SceneFileCodec(assets).load(config.default_scene)
    plan = SceneEditPlan(entities=[TaskEntity(entity_id="banana", semantic_name="banana", category="fruit")],
                        operations=[SceneEditIntent(operation="add", target="banana")])
    patch = SceneEditor(assets).edit(plan, scene, defaults=config.load_defaults())
    changed = SceneManager(scene).apply_patch(patch)
    assert changed.objects[:len(scene.objects)] == scene.objects
    props = next(c.properties for c in changed.objects[-1].components if c.component_type == "MetadataRef")
    assert props == {"path": "$LIBRARY_SERVER/2", "type": "model"}


def test_real_metadata_scale_and_color_mapping():
    assets=final_config().load_assets()
    apple=assets.resolve("$LIBRARY_SERVER/1","model")
    basket=assets.resolve("$LIBRARY_SERVER/4","model")
    assert apple.scalable is False and apple.scale_range==(1,1) and apple.color_tags==("red",)
    assert basket.scalable is True and basket.scale_range==(1,1.8) and basket.color_tags==("blue",)
    assert assets.resolve("$LIBRARY_SERVER/7","model").color_tags==("black","red")


def test_application_scale_restore_color_and_failure_keeps_dialogue(tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.contracts.turn import SceneEditPlan, SceneEditIntent, SceneQueryIntent
    from robot_agent_brain.scene.component_access import SceneIndex
    from test_application_artifacts import Provider
    entity=TaskEntity(entity_id="basket",semantic_name="basket",category="container",color="blue")
    create=BrainTurn(status="accepted",turn_kind="scene_edit",instruction="create",scene_edit=SceneEditPlan(
        entities=[entity],operations=[SceneEditIntent(operation="add",target="basket")]))
    config=final_config().model_copy(update={"provider":"replay","planner":"recipe","output_dir":str(tmp_path)})
    provider=Provider(create)
    app=BrainApplication(config,provider=provider)
    first=app.handle("create",session_id="edit")
    assert first.run_status=="success",first.reply
    original=app.get_session("edit").scene
    props=SceneIndex(original).transform(original.objects[-1].object_id_in_scene)
    assert props.scale==(1,1,1)
    provider.turn=BrainTurn(status="accepted",turn_kind="scene_edit",instruction="scale",scene_edit=SceneEditPlan(
        entities=[entity],operations=[SceneEditIntent(operation="scale",target="basket",scale_direction="enlarge",scale_amount="small")]))
    app=BrainApplication(config,provider=provider)
    second=app.handle("scale",session_id="edit")
    assert second.run_status=="success",second.reply
    assert second.scene_version==first.scene_version+1
    before=app.get_session("edit").scene.model_dump()
    dialogue=app.get_session("edit").dialogue.model_dump()
    provider.turn.scene_edit.operations=[SceneEditIntent(operation="update_properties",target="basket",properties={"color":"red"}),
        SceneEditIntent(operation="scale",target="basket",scale_mode="set",scale_xyz=[20]*3)]
    failed=app.handle("bad",session_id="edit")
    assert failed.run_status=="blocked"
    assert app.get_session("edit").scene.model_dump()==before
    assert app.get_session("edit").dialogue.model_dump()==dialogue
    assert "commands" not in failed.artifacts and "scene_patch" not in failed.artifacts
