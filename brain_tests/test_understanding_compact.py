import json
from copy import deepcopy

import httpx
import pytest
from jsonschema import ValidationError

from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest, parse_qwen_turn
from robot_agent_brain.models.understanding_wire import VERSION, encode, decode, compact_schema, compact_prompt


def entity(name="apple"):
    return {"entity_id": name, "semantic_name": name, "category": "fruit"}


def query():
    return {"protocol_version": "task_understanding.v3.1", "status": "accepted",
            "turn_kind": "scene_query", "scene_query": {
                "query_type": "count", "entities": [entity()], "target": "apple", "relations": []}}


@pytest.mark.parametrize("value", [query(),
    {"status": "clarification_required", "turn_kind": "robot_task", "clarification_question": "哪个苹果？"},
    {"status": "accepted", "turn_kind": "robot_task", "initial_robot_asset": "ur10",
     "entities": [entity(), entity("basket")], "operations": [{"operation": "pick_and_place",
       "source": "apple", "destination": "basket", "placement_target": {
           "kind": "container_interior", "reference": "basket", "relation": "inside"}}]},
    {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "scene_basis": "original", "entities": [entity()], "relations": [],
        "operations": [{"operation": "update_properties", "target": "apple", "properties": {"color": "blue"}}]}},
    {"status": "accepted", "turn_kind": "session_control", "session_control": {"action": "pause"}},
])
def test_canonical_roundtrip(value):
    full = {"protocol_version": "task_understanding.v3.1", **value}
    expanded = decode(encode(full))
    assert parse_qwen_turn(expanded, "test").model_dump() == parse_qwen_turn(full, "test").model_dump()


def test_values_not_rewritten():
    value = query()
    value["scene_query"]["entities"][0].update(entity_id="source", semantic_name="source")
    value["scene_query"]["target"] = "source"
    assert decode(encode(value))["scene_query"]["target"] == "source"
    assert decode(encode(value))["scene_query"]["entities"][0]["semantic_name"] == "source"


def test_only_optional_defaults_omitted():
    value = query()
    value.update(scene_edit=None, relations=[], arm_usage="unspecified")
    encoded = encode(value)
    assert "se" not in encoded and "r" not in encoded and "au" not in encoded
    assert encoded["s"] == "accepted" and encoded["k"] == "scene_query"


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(unknown=1), lambda x: x.pop("k"), lambda x: x.pop("s"),
    lambda x: x.update(v="task_understanding.v3.1"),
    lambda x: x["sq"].update(target="apple"), lambda x: x["sq"].pop("t"),
])
def test_bad_wire_rejected(mutate):
    wire = encode(query()); mutate(wire)
    with pytest.raises((ValueError, ValidationError)):
        decode(wire)


def test_empty_route_still_rejected():
    with pytest.raises(Exception):
        parse_qwen_turn(decode({"v": VERSION, "s": "accepted", "k": "scene_edit"}), "add")


def test_catalog_only_once_and_revision_matches():
    catalog = AssetCatalogSnapshot.from_items([CatalogAsset(asset_key="model:1", name="apple",
        selectable_for_add=True, scalable=False, scale_range=(1, 1))], [])
    provider = QwenHTTPProvider("http://test", "test")
    request = TaskUnderstandingRequest(instruction="增加苹果", asset_catalog=catalog)
    stage = provider.build_understanding_request(request)
    payload = json.loads(stage.content)
    assert "asset_catalog" not in payload
    assert payload["catalog_revision"] == catalog.revision
    assert stage.prompt.count("- model:1 |") == 1
    assert "scalable=False" in stage.prompt and "scale_range=(1.0, 1.0)" in stage.prompt
    assert request.asset_catalog == catalog


def test_http_compact_is_expanded_and_raw_preserved():
    wire = encode(query())
    def handler(req):
        payload = json.loads(req.content)
        assert payload["response_format"]["json_schema"]["schema"] == compact_schema()
        return httpx.Response(200, json={"id": "completion-test", "timings": {"prompt_ms": 5},
            "choices": [{"message": {"content": json.dumps(wire)}, "finish_reason": "stop"}]})
    provider = QwenHTTPProvider("http://test", "test", transport=httpx.MockTransport(handler),
        understanding_wire_format="compact_v1")
    result = provider.understand_turn(TaskUnderstandingRequest(instruction="有几个苹果"))
    assert result.turn_kind.value == "scene_query"
    assert provider.last_raw_values["task_understanding"] == wire
    assert provider.last_raw_values["task_understanding_canonical"]["turn_kind"] == "scene_query"
    assert provider.calls[-1]["server_timings"] == {"prompt_ms": 5}


def test_no_silent_legacy_fallback():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(query())}}]})
    provider = QwenHTTPProvider("http://test", "test", transport=httpx.MockTransport(handler),
        understanding_wire_format="compact_v1")
    with pytest.raises(QwenProviderError) as exc:
        provider.understand_turn(TaskUnderstandingRequest(instruction="有几个苹果"))
    assert exc.value.code == "provider_output_schema_invalid"


def test_prompt_keeps_action_values_and_removes_legacy_envelope():
    prompt = compact_prompt(TASK_UNDERSTANDING_PROMPT)
    assert 'v="u.compact.v1"' in prompt
    assert '"turn_kind": "scene_edit"' not in prompt
    assert "pick_and_place" in prompt
    assert "顶层必须包含" not in prompt


@pytest.mark.parametrize("operation", [
    {"operation": "add", "target": "apple", "relation": "on"},
    {"operation": "add"},
    {"operation": "replace", "target": "apple"},
    {"operation": "translate", "target": "missing", "direction": "right", "distance_m": 0.02},
])
def test_missing_semantics_never_filled(operation):
    full = {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [entity()], "operations": [operation]}}
    with pytest.raises(Exception):
        parse_qwen_turn(decode(encode(full)), "test")


def test_live_missing_asset_choices_retries_same_wire_then_rejects():
    catalog = AssetCatalogSnapshot.from_items([CatalogAsset(asset_key="model:1", name="apple",
        selectable_for_add=True)], [])
    wire = encode({"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [entity()], "operations": [{"operation": "add", "target": "apple"}]}})
    requests = []
    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(wire)}, "finish_reason": "stop"}]})
    provider = QwenHTTPProvider("http://test", "test", transport=httpx.MockTransport(handler),
                               understanding_wire_format="compact_v1")
    with pytest.raises(QwenProviderError) as exc:
        provider.understand_turn(TaskUnderstandingRequest(instruction="增加苹果", asset_catalog=catalog))
    assert exc.value.code == "asset_choice_missing"
    assert len(requests) == 2
    assert "se.ch" in requests[1]["messages"][0]["content"]
    assert requests[0]["response_format"] == requests[1]["response_format"]


def test_legacy_understand_uses_same_codec():
    wire = encode({"status": "accepted", "turn_kind": "robot_task", "entities": [entity(), entity("basket")],
        "operations": [{"operation": "pick_and_place", "source": "apple", "destination": "basket",
                        "placement_target": {"kind": "container_interior", "reference": "basket", "relation": "inside"}}]})
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(wire)}}]})
    provider = QwenHTTPProvider("http://test", "test", transport=httpx.MockTransport(handler),
                               understanding_wire_format="compact_v1")
    assert provider.understand(TaskUnderstandingRequest(instruction="把苹果放入篮子")).operations


def test_prompt_color_property_remains_public_scene_field():
    prompt = compact_prompt(TASK_UNDERSTANDING_PROMPT)
    assert '"p":{"color":' in prompt
    assert '"p":{"cl":' not in prompt


@pytest.mark.parametrize("operation, instruction", [
    ({"operation": "add", "target": "apple", "relation": "on", "reference": "table", "placement_region": "right_half"}, "在桌面右侧增加两个苹果"),
    ({"operation": "replace", "target": "apple", "replacement_entity": "banana"}, "把苹果替换成香蕉"),
    ({"operation": "scale", "target": "apple", "scale_mode": "multiply", "scale_xyz": [1.1, 1.1, 1.1]}, "把苹果放大1.1倍"),
    ({"operation": "rotate", "target": "apple", "axis": "z", "angle_deg": 90}, "把苹果绕Z轴旋转90度"),
    ({"operation": "translate", "target": "apple", "direction": "right", "distance_m": .02}, "把苹果向右移动两厘米"),
    ({"operation": "move_relative", "target": "apple", "relation": "near", "reference": "banana"}, "把苹果移动到香蕉旁边"),
    ({"operation": "remove", "target": "apple"}, "删除这个苹果"),
])
def test_edit_features_preserve_canonical_semantics(operation, instruction):
    full = {"protocol_version": "task_understanding.v3.1", "status": "accepted", "turn_kind": "scene_edit",
            "scene_edit": {"scene_basis": "original", "entities": [entity(), entity("banana")],
                           "operations": [operation]}}
    assert parse_qwen_turn(decode(encode(full)), instruction).model_dump() == parse_qwen_turn(full, instruction).model_dump()


def test_robot_config_and_initial_edit_extension():
    value = {"status": "accepted", "turn_kind": "robot_config", "robot_asset_switch": {"robot_asset": "ur10"}}
    expanded = decode(encode(value))
    assert expanded == {"protocol_version": "task_understanding.v3.1", **value}
    # Runtime robot switching is already rejected by the canonical parser;
    # a compact transport must not silently add that capability.
    for payload in (expanded, {"protocol_version": "task_understanding.v3.1", **value}):
        with pytest.raises(ValueError):
            parse_qwen_turn(payload, "切换UR10")
    value = {"status": "accepted", "turn_kind": "scene_edit", "initial_robot_asset": "ur10", "scene_edit": {
        "entities": [entity()], "operations": [{"operation": "add", "target": "apple"}]}}
    assert parse_qwen_turn(decode(encode(value)), "使用UR10并增加苹果").initial_robot_asset == "ur10"


@pytest.mark.parametrize("wire", [
    {"v": VERSION, "s": "accepted", "k": "robot_task", "e": [{"id": "a", "n": "apple", "c": "fruit"}]},
    {"v": VERSION, "s": "accepted", "k": "scene_edit", "se": None},
    {"v": VERSION, "s": "clarification_required", "k": "robot_task", "q": "哪个？", "o": []},
    {"v": VERSION, "s": "accepted", "k": "scene_edit", "se": {"e": [{"id": "a", "n": "apple", "c": "fruit"}],
        "o": [{"op": "update_properties", "t": "a", "p": {"cl": "blue"}}]}},
])
def test_route_and_property_schema_rejects_before_canonical_parser(wire):
    with pytest.raises(ValidationError):
        decode(wire)


def test_invalid_next_response_does_not_retain_previous_canonical_debug():
    responses = iter([encode(query()), {"v": VERSION, "unexpected": True}])
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(next(responses))}}]})
    provider = QwenHTTPProvider("http://test", "test", transport=httpx.MockTransport(handler),
                               understanding_wire_format="compact_v1")
    request = TaskUnderstandingRequest(instruction="有几个苹果")
    provider.understand_turn(request)
    assert "task_understanding_canonical" in provider.last_raw_values
    with pytest.raises(QwenProviderError):
        provider.understand_turn(request)
    assert "task_understanding_canonical" not in provider.last_raw_values
    assert "task_understanding_canonical" not in provider.last_raw_text


def test_omitted_null_and_empty_are_field_specific_not_interchangeable():
    wire = encode(query())
    # Omission uses the canonical entity's declared count=1 default.
    assert parse_qwen_turn(decode(wire), "有几个苹果").scene_query.entities[0].count == 1
    bad = deepcopy(wire)
    bad["sq"]["e"][0]["ct"] = None
    with pytest.raises(ValidationError):
        decode(bad)
    bad = deepcopy(wire)
    bad["sq"]["e"] = None
    with pytest.raises(ValidationError):
        decode(bad)
    bad = deepcopy(wire)
    bad["sq"]["e"] = []
    with pytest.raises((ValueError, ValidationError)):
        parse_qwen_turn(decode(bad), "有几个苹果")
    # Optional predicate null is allowed for a non-relation query.
    wire["sq"]["pd"] = None
    assert parse_qwen_turn(decode(wire), "有几个苹果").scene_query.predicate is None


def test_constructor_catalog_also_validates_direct_call_asset_choices():
    catalog = AssetCatalogSnapshot.from_items([CatalogAsset(asset_key="model:1", name="apple",
                                                           selectable_for_add=True)], [])
    value = {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [entity()], "operations": [{"operation": "add", "target": "apple"}],
        "asset_choices": [{"entity_id": "apple", "asset_key": "model:999"}]}}
    def handler(request):
        assert json.loads(json.loads(request.content)["messages"][1]["content"])["catalog_revision"] == catalog.revision
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(encode(value))}}]})
    provider = QwenHTTPProvider("http://test", "test", asset_catalog=catalog,
                               transport=httpx.MockTransport(handler), understanding_wire_format="compact_v1")
    with pytest.raises(QwenProviderError):
        provider.understand_turn(TaskUnderstandingRequest(instruction="增加苹果"))
