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


def test_the_pronoun_a_split_leaves_alone_binds_the_object_that_split_added():
    """「再新增一个香蕉，把它放到篮子里」 names one determinate object, not two candidates.

    Every subtask of one sentence walks through the same session, so the focus the add
    left behind is what 「它」 resolves to.  That is only reachable while the split keeps
    the pronoun: rewriting it to 「香蕉」 -- what step 4 of the five-clause run got -- turns a
    determinate reference into a name that matches both bananas and the walk stops to ask
    which one.  「他」 is the same pronoun mistyped, and 「其他」 is not a pronoun at all.
    """
    from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
    from robot_agent_brain.session.brain_session import BrainSession
    session = BrainSession(supported_scene(), BrainPipeline(None, BrainConfig().load_assets()),
                           MockScenePlatform())
    added = session.process_turn("add", BrainTurn(status="accepted", turn_kind="scene_edit",
        instruction="新增一个香蕉", scene_edit=SceneEditPlan(entities=[
            TaskEntity(entity_id="a", semantic_name="apple", category="fruit"),
            TaskEntity(entity_id="b", semantic_name="banana", category="fruit")],
            operations=[SceneEditIntent(operation="add", target="b", reference="a",
                                        relation="right_of")])))
    assert len(added.focus_object_ids) == 1
    assert session.dialogue.last_entity_id == added.focus_object_ids[0]
    assert session.dialogue.contextualize("把它放到篮子里", session.scene) == "把它放到篮子里 [dialogue_ref=banana]"
    assert session.dialogue.contextualize("再把他拿出来", session.scene) == "再把他拿出来 [dialogue_ref=banana]"
    assert "[dialogue_ref" not in session.dialogue.contextualize("把其他的香蕉改成绿色", session.scene)


def test_color_then_robot_pronoun_keeps_the_selected_object():
    """The first edit's unique focus is the source of the following robot step."""
    from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
    from robot_agent_brain.session.brain_session import BrainSession
    session = BrainSession(supported_scene(), BrainPipeline(None, BrainConfig().load_assets()),
                           MockScenePlatform())
    first = session.process_turn("color", BrainTurn(status="accepted", turn_kind="scene_edit",
        instruction="把最左边的苹果改成绿色", scene_edit=SceneEditPlan(entities=[
            TaskEntity(entity_id="apple", semantic_name="apple", category="fruit", count=1,
                       quantity_mode="candidate_pool", select_count_from_candidates=True),
        ], operations=[SceneEditIntent(operation="update_properties", target="apple",
                                       properties={"color": "green"})])))
    assert first.focus_object_ids == [1]
    assert session.dialogue.last_entity_id == 1
    assert session.dialogue.contextualize("把他放到托盘里", session.scene) == "把他放到托盘里 [dialogue_ref=apple]"


def test_unresolved_cross_turn_pronoun_still_rejected():
    class Provider:
        def understand_turn(self, request):
            return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=request.instruction,
                scene_edit=SceneEditPlan(entities=[TaskEntity(entity_id="a", semantic_name="apple", category="fruit", dialogue_ref=True)],
                    operations=[SceneEditIntent(operation="translate", target="a", direction="right", distance_m=.1)]))
    with pytest.raises(ValueError, match="dialogue_reference_missing"):
        BrainPipeline(Provider(), BrainConfig().load_assets()).understand_turn("把它右移十厘米",
            scene=SceneConfig(scene_schema_version=1, scene_version=0, scene_id=1, scene_name="s", objects=[]), dialogue=DialogueState())
