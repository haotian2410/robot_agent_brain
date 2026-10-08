import pytest
from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.model_property import ModelProperty
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditPlan, SceneEditIntent
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.session.dialogue_state import DialogueState
from robot_agent_brain.config import BrainConfig
from test_query_scene_continuity import supported_scene


def test_understanding_allows_local_add_reference_without_previous_focus():
    class Provider:
        count = 0
        def understand_turn(self, request):
            self.count += 1
            assert "dialogue_scene_object_id" not in request.instruction
            return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=request.instruction,
                scene_edit=SceneEditPlan(entities=[TaskEntity(entity_id="a", semantic_name="apple", category="fruit"),
                    TaskEntity(entity_id="b", semantic_name="banana", category="fruit", dialogue_ref=True)], operations=[
                    SceneEditIntent(operation="add", target="b", reference="a", relation="right_of"),
                    SceneEditIntent(operation="translate", target="b", direction="right", distance_m=.1)]))
    assets = BrainConfig().load_assets()
    scene = supported_scene()
    scene.objects.pop()
    provider = Provider()
    result = BrainPipeline(provider, assets).run("r", "在苹果右边添加香蕉，然后把它右移十厘米", scene, dialogue=DialogueState())
    assert provider.count == 1
    assert [op.action for op in result.scene_patch.operations] == ["add_object", "upsert_component", "upsert_component", "upsert_component"]
    assert len({op.object_id_in_scene for op in result.scene_patch.operations}) == 1


def test_unresolved_cross_turn_pronoun_still_rejected():
    class Provider:
        def understand_turn(self, request):
            return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=request.instruction,
                scene_edit=SceneEditPlan(entities=[TaskEntity(entity_id="a", semantic_name="apple", category="fruit", dialogue_ref=True)],
                    operations=[SceneEditIntent(operation="translate", target="a", direction="right", distance_m=.1)]))
    with pytest.raises(ValueError, match="dialogue_reference_missing"):
        BrainPipeline(Provider(), BrainConfig().load_assets()).understand_turn("把它右移十厘米",
            scene=SceneConfig(scene_schema_version=1, scene_version=0, scene_id=1, scene_name="s", objects=[]), dialogue=DialogueState())
