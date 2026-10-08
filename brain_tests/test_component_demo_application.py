import json
from pathlib import Path

import pytest

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.commands import CommandsFile
from robot_agent_brain.contracts.task_intent import TaskIntent, TaskEntity, Operation, PlacementTarget
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditPlan, SceneEditIntent, SceneQueryIntent


def entity(identifier, name, category):
    return TaskEntity(entity_id=identifier, semantic_name=name, category=category)


class DemoUnderstanding:
    def understand_turn(self, request):
        if request.instruction == "放苹果":
            return BrainTurn(status="accepted", turn_kind="robot_task", instruction=request.instruction,
                task_intent=TaskIntent(instruction=request.instruction,
                    entities=[entity("apple", "apple", "fruit"), entity("box", "box", "container")],
                    operations=[Operation(operation_id="op-1", task_type="pick_and_place", source="apple",
                        destination="box", placement_target=PlacementTarget(kind="container_interior", reference="box"))]))
        if request.instruction == "增加香蕉":
            return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=request.instruction,
                scene_edit=SceneEditPlan(entities=[entity("banana", "banana", "fruit"), entity("apple", "apple", "fruit")],
                    operations=[SceneEditIntent(operation="add", target="banana", relation="right_of", reference="apple")]))
        return BrainTurn(status="accepted", turn_kind="scene_query", instruction=request.instruction,
            scene_query=SceneQueryIntent(query_type="count", entities=[entity("banana", "banana", "fruit")], target="banana"))


def test_demo_bootstrap_edit_query_restart_and_wire_artifacts(tmp_path):
    config = BrainConfig(provider="replay", output_dir=str(tmp_path), debug=True)
    app = BrainApplication(config, provider=DemoUnderstanding())
    first = app.handle("放苹果", session_id="demo")
    assert first.run_status == "success", first.reply
    assert first.executed is False
    assert first.delivery_status == "commands_exported"
    scene = SceneConfig.model_validate_json(Path(first.artifacts["scene_config"]).read_text())
    commands = CommandsFile.model_validate_json(Path(first.artifacts["commands"]).read_text())
    assert isinstance(scene.scene_id, int)
    assert commands.scene_id == scene.scene_id
    assert all(type(command.parameters.target) is int for command in commands.commands)
    refs = [c.properties["path"] for obj in scene.objects for c in obj.components if c.component_type == "MetadataRef"]
    assert all(ref.startswith("$DEMO_LIBRARY/") for ref in refs)
    assert any("demo_assets" in assumption for assumption in first.assumptions)
    second = app.handle("增加香蕉", session_id="demo")
    assert second.run_status == "success", second.reply
    assert "commands" not in second.artifacts
    assert second.scene_version == scene.scene_version + 1
    patch = json.loads(Path(second.artifacts["scene_patch"]).read_text())
    assert patch["operations"][0]["action"] == "add_object"
    app = BrainApplication(config, provider=DemoUnderstanding())
    third = app.handle("几个香蕉", session_id="demo")
    assert third.run_status == "success", third.reply
    assert json.loads(Path(third.artifacts["query_result"]).read_text())["count"] == 1
    assert third.executed is False


def test_demo_resolver_cannot_resolve_formal_references():
    assets = BrainConfig().load_assets()
    assert assets.demo_assets
    assert assets.resolve("$DEMO_LIBRARY/2").semantic_name == "apple"
    with pytest.raises(LookupError, match="asset_missing"):
        assets.resolve("$LIBRARY_SERVER/1")


def test_real_library_settings_never_inherit_demo_platform():
    config = BrainConfig(asset_library_root="/configured/assets", asset_geometry_cache="/configured/cache.json")
    assert config.bootstrap_settings() == {}
