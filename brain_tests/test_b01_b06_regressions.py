import json
import math
import httpx
import pytest
from pydantic import ValidationError
from robot_agent_brain.contracts.asset_library import BrainAssetView
from robot_agent_brain.contracts.scene import SceneConfig, SceneComponent
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.contracts.turn import SceneQueryIntent
from robot_agent_brain.scene.query import SceneQueryEngine
from robot_agent_brain.web.camera_policy import choose_camera
from robot_agent_brain.web.gateway import GatewayScenePlatformAdapter
from robot_agent_brain.web.protocol import digest
from robot_agent_brain.models.task_understanding import parse_qwen_turn
from robot_agent_brain.errors import SceneCommitRejected
from test_component_runtime import object_
from test_web_gateway import Browser, adapter
from test_original_scene_commit import session_store


class Assets:
    def resolve(self, ref, kind=None):
        return BrainAssetView(library_asset_id=1, metadata_ref=ref, semantic_name="fixture",
            dimensions_m=(.1, .1, .1), local_aabb_min_m=(-.05, -.05, 0), local_aabb_max_m=(.05, .05, .1))


def fixture():
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="query", objects=[
        object_(0, "work_table", "surface"),
        object_(1, "basket", "container", metadata_ref="basket", support=0),
        object_(2, "apple", position=(-.3, 0, 0), metadata_ref="apple", support=0),
        object_(3, "apple", position=(.6, 0, 0), metadata_ref="apple", support=0)])


def entities():
    return [TaskEntity(entity_id="apple", semantic_name="apple", category="fruit"),
            TaskEntity(entity_id="basket", semantic_name="basket", category="container")]


def test_near_boundary_and_not_inside_or_reference():
    scene = fixture()
    q = SceneQueryIntent(query_type="neighbors", target="basket", entities=entities())
    result = SceneQueryEngine(assets=Assets()).query(q, scene)
    assert result.object_ids == [2] and math.isclose(result.distances_m[2], .2)
    assert "20 厘米" in result.reply
    assert result.reference_object_id == 1 and scene.scene_version == 1
    scene.objects[2].components[0].properties["position"] = [0, 0, .02]
    assert SceneQueryEngine(assets=Assets()).query(q, scene).object_ids == []


def test_query_missing_geometry_is_not_false():
    with pytest.raises(ValueError, match="query_geometry_evidence_missing"):
        SceneQueryEngine().query(SceneQueryIntent(query_type="neighbors", target="basket", entities=entities()), fixture())


def test_imported_and_added_apples_remain_one_candidate_set():
    from robot_agent_brain.scene.component_access import SceneIndex
    scene = fixture()
    SceneIndex(scene).component(2, "Semantic").properties["category"] = "object"
    query = SceneQueryIntent(query_type="selection", target="apple", entities=entities(), relations=[
        {"subject": "apple", "relation": "nearest", "reference": "basket"}])
    assert SceneQueryEngine().query(query, scene).object_ids == [2]
    count = SceneQueryIntent(query_type="count", target="apple", entities=entities())
    assert len(SceneQueryEngine().query(count, scene).object_ids) == 2


@pytest.mark.parametrize("relation,expected", [("nearest", [2]), ("farthest", [3])])
def test_multi_candidate_distance_selection(relation, expected):
    query = SceneQueryIntent(query_type="selection", target="apple", entities=entities(), relations=[
        {"subject": "apple", "relation": relation, "reference": "basket"}])
    result = SceneQueryEngine().query(query, fixture())
    assert result.object_ids == expected and "水平中心距离" in result.reply
    scene = fixture()
    scene.objects[3].components[0].properties["position"] = [.3, 0, 0]
    tied = SceneQueryEngine().query(query, scene)
    assert tied.object_ids == [2, 3] and "并列" in tied.reply


@pytest.mark.parametrize("predicate,answer", [("left_of", True), ("right_of", False)])
def test_boolean_relation_not_position_filter(predicate, answer):
    scene = fixture()
    scene.objects.pop()
    query = SceneQueryIntent(query_type="relation", target="apple", reference="basket", predicate=predicate, entities=entities())
    result = SceneQueryEngine().query(query, scene)
    assert result.relation_holds is answer and result.reply.startswith("是" if answer else "否")


def test_query_ambiguous_subject_does_not_return_false():
    query = SceneQueryIntent(query_type="relation", target="apple", reference="basket", predicate="left_of", entities=entities())
    with pytest.raises(ValueError, match="query_reference_ambiguous"):
        SceneQueryEngine().query(query, fixture())


def test_only_qwen_invalid_near_becomes_clarification():
    value = {"status": "accepted", "turn_kind": "scene_query", "scene_query": {
        "query_type": "position", "entities": [entities()[1].model_dump(mode="json")],
        "target": "basket", "relations": [{"subject": "basket", "relation": "near", "reference": None}]}}
    assert parse_qwen_turn(value, "篮子旁边有什么").status == "clarification_required"
    with pytest.raises(ValidationError):
        SceneQueryIntent.model_validate(value["scene_query"])


def test_selection_wire_nesting_does_not_guess_missing_reference():
    query = {"query_type": "selection", "target": "apple", "entities": [e.model_dump(mode="json") for e in entities()]}
    value = {"status": "accepted", "turn_kind": "scene_query", "scene_query": query,
             "relations": [{"subject": "apple", "relation": "nearest", "reference": "basket"}]}
    assert parse_qwen_turn(value, "哪个苹果离篮子最近").scene_query.relations[0].reference == "basket"
    value["relations"][0]["reference"] = None
    assert parse_qwen_turn(value, "哪个苹果离篮子最近").status == "clarification_required"
    with pytest.raises(ValidationError, match="explicit_selector"):
        SceneQueryIntent.model_validate(query)


def test_camera_overhead_not_first_and_ambiguous_no_guess():
    scene = fixture()
    for i, name in [(4, "wrist_camera_d435i"), (5, "overhead_camera_d435i")]:
        obj = object_(i, name, "camera")
        obj.components.append(SceneComponent(component_type="Camera", properties={}))
        scene.objects.append(obj)
    assert choose_camera(scene) == (5, "explicit_overhead_semantic")
    scene.objects[-1].components[1].properties["semantic_name"] = "unknown"
    assert choose_camera(scene)[0] is None


def test_confirmed_rejection_keeps_original_session_synchronized(tmp_path):
    session, store = session_store(tmp_path)
    before = session.scene
    class Reject:
        def load_scene(self, scene):
            raise SceneCommitRejected("gateway_commit_rejected")
    session.platform = Reject()
    with pytest.raises(SceneCommitRejected):
        session.derive_original_scene(store, lambda s: s, reset_allowed=True)
    assert session.sync_state == "synchronized" and session.scene == before


@pytest.mark.parametrize("confirmed", [True, False])
def test_lease_503_requires_attributed_no_grant_evidence(confirmed):
    def respond(request):
        value = {"error": {"code": "NO_BROWSER_CONNECTED"}}
        if confirmed:
            value.update(lease_status="not_granted", taskID=7, browserID="b", sessionID="s")
        return httpx.Response(503, json=value)
    platform = GatewayScenePlatformAdapter("http://127.0.0.1:8099", "b", session_id="s",
                                          client=httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(httpx.HTTPStatusError):
        platform.acquire_lease(7, fixture())
    assert platform.lease_uncertain is not confirmed


def test_incomplete_rejection_and_wrong_ack_stay_unknown(tmp_path):
    browser = Browser()
    platform = adapter(browser, tmp_path)
    platform.adopt(browser.scene)
    browser.fault = "wrong_receipt"
    with pytest.raises(ValueError, match="gateway_commit_receipt_invalid"):
        platform.load_scene(browser.scene.model_copy(update={"scene_version": 1}))
    records = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    assert records and records[0]["status"] == "unknown"
