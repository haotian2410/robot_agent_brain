import json

import httpx

from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan, TurnKind, TurnStatus
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.batch_service import _classify_batch_error
from robot_agent_brain.batch import BatchSession


def _v31_scene_edit(*, with_choice=True):
    payload = {
        "protocol_version": "task_understanding.v3.1",
        "status": "accepted",
        "turn_kind": "scene_edit",
        "clarification_question": None,
        "scene_edit": {
            "scene_basis": "current",
            "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "relations": [],
            "operations": [{"operation": "add", "target": "apple", "relation": "on", "reference": "table"}],
            "asset_choices": ([{"entity_id": "apple", "asset_key": "model:1"}] if with_choice else []),
        },
        "scene_query": None, "session_control": None, "robot_setup_request": None,
        "entities": [], "operations": [], "relations": [],
    }
    return payload


def test_live_missing_asset_choice_gets_one_bounded_repair_call():
    snapshot = AssetCatalogSnapshot.from_items([
        CatalogAsset(asset_key="model:1", name="apple", selectable_for_add=True),
    ], [])
    responses = [_v31_scene_edit(with_choice=False), _v31_scene_edit(with_choice=True)]
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(responses.pop(0))}, "finish_reason": "stop"}],
        })

    provider = QwenHTTPProvider("http://example/v1", "qwen-test", transport=httpx.MockTransport(handler))
    turn = provider.understand_turn(TaskUnderstandingRequest(
        instruction="增加一个苹果", asset_catalog=snapshot))
    assert turn.scene_edit is not None
    assert len(requests) == 2
    assert len(provider.calls) == 2
    assert "asset_choices" in requests[1]["messages"][0]["content"]


def test_live_missing_asset_choice_stops_after_one_repair_attempt():
    snapshot = AssetCatalogSnapshot.from_items([
        CatalogAsset(asset_key="model:1", name="apple", selectable_for_add=True),
    ], [])
    raw = _v31_scene_edit(with_choice=False)
    provider = QwenHTTPProvider(
        "http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(raw)}, "finish_reason": "stop"}],
        })),
    )
    import pytest
    with pytest.raises(QwenProviderError) as exc:
        provider.understand_turn(TaskUnderstandingRequest(
            instruction="增加一个苹果", asset_catalog=snapshot))
    assert exc.value.code == "asset_choice_missing"
    assert len(provider.calls) == 2


class _Provider:
    def __init__(self, turn):
        self.turn = turn

    def understand_turn(self, request):
        return self.turn


def test_unambiguous_existence_language_cannot_execute_scene_edit():
    plan = SceneEditPlan(
        entities=[TaskEntity(entity_id="pen", semantic_name="pen", category="tool")],
        relations=[],
        operations=[SceneEditIntent(operation="add", target="pen", relation="on", reference="table")],
    )
    turn = BrainTurn(status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SCENE_EDIT,
                     instruction="有没有蓝色钢笔", scene_edit=plan)
    pipeline = BrainPipeline(_Provider(turn), object())
    result = pipeline.understand_turn("有没有蓝色钢笔")
    assert result.turn_kind == TurnKind.SCENE_QUERY
    assert result.scene_edit is None
    assert result.scene_query is not None
    assert result.scene_query.query_type == "existence"


def test_explicit_edit_language_remains_scene_edit():
    plan = SceneEditPlan(
        entities=[TaskEntity(entity_id="pen", semantic_name="pen", category="tool")],
        relations=[],
        operations=[SceneEditIntent(operation="add", target="pen", relation="on", reference="table")],
    )
    turn = BrainTurn(status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SCENE_EDIT,
                     instruction="增加一个钢笔", scene_edit=plan)
    pipeline = BrainPipeline(_Provider(turn), object())
    result = pipeline.understand_turn("增加一个钢笔")
    assert result.turn_kind == TurnKind.SCENE_EDIT
    assert result.scene_edit is not None


def test_unregistered_robot_codes_are_capability_boundaries():
    for code in ("robot_setup_profile_not_registered", "dual_planner_capability_unsupported",
                 "dual_recipe_capability_unsupported"):
        status, outcome, error = _classify_batch_error(RuntimeError(code))
        assert (status, outcome) == ("passed", "unsupported")
        assert error["code"] == code
        assert error["failure_class"] == "capability_unsupported"
        assert error["executed"] is False


def test_batch_fixture_preflight_skips_missing_target_before_gateway(tmp_path):
    scene = {"scene_schema_version": 1, "scene_id": 1, "scene_version": 1,
             "scene_name": "fixture", "objects": [{
                 "object_id_in_scene": 1, "object_name_in_scene": "table",
                 "components": [
                     {"component_type": "Transform", "properties": {
                         "position": [0, 0, 0], "quaternion_xyzw": [0, 0, 0, 1],
                         "scale": [1, 1, 1], "parent": None}},
                     {"component_type": "MetadataRef", "properties": {"path": "$LIBRARY_SERVER/29", "type": "model"}},
                     {"component_type": "Semantic", "properties": {"semantic_name": "table", "category": "surface", "support": None}},
                 ],
             }]}
    scene_path = tmp_path / "fixture.json"
    scene_path.write_text(json.dumps(scene), encoding="utf-8")
    runner = __import__("robot_agent_brain.batch_service", fromlist=["ServiceBatchRunner"]).ServiceBatchRunner(
        agent_url="http://agent", gateway_url="http://gateway", output_dir=tmp_path, screenshot_required=False)
    session = BatchSession(name="missing", scene="fixture.json", instructions=["缩放马克笔"],
                           expected_outcome="scene_updated",
                           expected_assertions={"operation": "scale", "target_role": "object_a"},
                           asset_role_mapping={"object_a": {"semantic_name": "marker", "scalable": True}})
    issue = runner._validate_session_fixture(tmp_path / "cases.json", session)
    assert issue and issue["code"] == "fixture_asset_missing"
