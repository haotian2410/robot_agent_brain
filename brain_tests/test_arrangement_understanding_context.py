from robot_agent_brain.scene.arrangement_index import ArrangementIndex, ArrangementRecord
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.contracts.turn import BrainTurn
from test_layout_transaction import setup


def test_membership_context_is_scene_scoped_and_marks_deleted_members():
    scene, _, _ = setup()
    index = ArrangementIndex()
    index.put(ArrangementRecord(arrangement_id="arr-existing", scene_id=scene.scene_id,
        scene_version=scene.scene_version, slot_bindings={"s0": 0, "s1": 99},
        slot_assets={"s0": "table", "s1": "apple"}, world_positions={"s0": (1, 2)}))
    index.put(ArrangementRecord(arrangement_id="arr-other-scene", scene_id=scene.scene_id + 1,
        scene_version=1, slot_bindings={"s0": 0}))
    before = index.snapshot()
    context = index.understanding_context(scene)
    assert len(context) == 1
    assert context[0]["arrangement_id"] == "arr-existing"
    assert context[0]["members_complete"] is False
    assert [slot["exists"] for slot in context[0]["slots"]] == [True, False]
    assert "world_positions" not in context[0]
    context[0]["slots"][0]["object_id"] = 999
    assert index.snapshot() == before
    assert index.understanding_context(None) == []


def test_understanding_receives_session_index_without_shared_pipeline_state():
    scene, _, editor = setup()
    requests = []
    class Provider:
        def understand_turn(self, request):
            requests.append(request)
            return BrainTurn(status="clarification_required", turn_kind="scene_layout",
                instruction=request.instruction, clarification_question="哪一组？")
    pipeline = BrainPipeline(Provider(), editor.assets, scene_editor=editor)
    index = ArrangementIndex()
    index.put(ArrangementRecord(arrangement_id="arr-existing", scene_id=scene.scene_id,
        scene_version=scene.scene_version, slot_bindings={"s0": 0}))
    pipeline.understand_turn("重排这一组", scene=scene, arrangement_index=index)
    pipeline.understand_turn("排列另一组", scene=scene)
    assert requests[0].scene_context["arrangements"][0]["arrangement_id"] == "arr-existing"
    assert requests[1].scene_context["arrangements"] == []
