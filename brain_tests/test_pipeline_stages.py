import pytest

from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.scene import ModelProperty, SceneConfig, SceneObject
from robot_agent_brain.contracts.task_intent import TaskIntent, TaskEntity, Operation
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneQueryIntent, SessionControlIntent, SceneEditPlan
from robot_agent_brain.pipeline import BrainPipeline


class SpyProvider:
    def __init__(self, turn):
        self.turn = turn
        self.requests = []

    def understand_turn(self, request):
        self.requests.append(request)
        return self.turn


def fixture_pipeline(kind):
    payload = {
        "robot_task": dict(task_intent=TaskIntent(instruction="抓起苹果", entities=[
            TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")],
            operations=[Operation(operation_id="op-1", task_type="grasp", target="apple")])),
        "scene_edit": dict(scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=1, quantity_mode='single')], operations=[SceneEditIntent(operation='translate', direction='right', distance_m=0.1, target="target")])),
        "scene_query": dict(scene_query=SceneQueryIntent(query_type="count", target="apple", entities=[dict(entity_id="apple", semantic_name="apple", category="fruit")])),
        "session_control": dict(session_control=SessionControlIntent(action="pause")),
    }[kind]
    turn = BrainTurn(status="accepted", turn_kind=kind, instruction="provider text", **payload)
    provider = SpyProvider(turn)
    assets = LocalAssetCatalog([ModelProperty(asset_id="apple", semantic_name="apple", category="fruit",
                                             dimensions_m=(.1, .1, .1))])
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="apple_01", asset_id="apple",
                                                          semantic_name="apple", category="fruit")])
    return BrainPipeline(provider, assets), provider, scene


@pytest.mark.parametrize("kind,text", [("robot_task", "抓起苹果"), ("scene_edit", "苹果右移十厘米")])
@pytest.mark.parametrize("initial_scene", [True, False])
def test_understand_once_then_process_with_available_scene(kind, text, initial_scene):
    pipeline, provider, scene = fixture_pipeline(kind)
    turn = pipeline.understand_turn(text, scene=scene if initial_scene else None)
    assert len(provider.requests) == 1
    assert turn.instruction == text
    # The future bootstrap step supplies a scene here, without another understanding.
    result = pipeline.process_turn("r", turn, scene)
    assert len(provider.requests) == 1
    assert result.turn_kind == kind


@pytest.mark.parametrize("kind", ["robot_task", "scene_edit", "scene_query", "session_control"])
def test_direct_process_never_calls_provider(kind):
    pipeline, provider, scene = fixture_pipeline(kind)
    if kind in {"scene_query", "session_control"}:
        def forbidden(*args, **kwargs):
            raise AssertionError("query/control must not plan skills")
        pipeline.planner.plan = forbidden
    result = pipeline.process_turn("r", provider.turn, None if kind == "session_control" else scene)
    assert result.turn_kind == kind
    assert not provider.requests


def test_context_markers_do_not_replace_original_instruction():
    pipeline, provider, scene = fixture_pipeline("robot_task")
    class Context:
        def contextualize(self, text, scene):
            return text + " [dialogue_ref=apple]"
    turn = pipeline.understand_turn("抓起它", scene=scene, dialogue=Context())
    assert provider.requests[0].instruction.endswith("[dialogue_ref=apple]")
    assert turn.instruction == turn.task_intent.instruction == "抓起它"


def test_compatibility_run_calls_understanding_once():
    pipeline, provider, scene = fixture_pipeline("robot_task")
    assert pipeline.run("r", "抓起苹果", scene).commands is not None
    assert len(provider.requests) == 1
