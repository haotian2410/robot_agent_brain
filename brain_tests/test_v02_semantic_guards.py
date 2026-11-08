from robot_agent_brain.models.task_understanding import parse_qwen_turn
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest


def _envelope(operations):
    return {
        "protocol_version": "task_understanding.v3.1",
        "status": "accepted", "turn_kind": "scene_edit",
        "clarification_question": None, "arm_usage": "unspecified",
        "scene_edit": {
            "scene_basis": "current",
            "entities": [
                {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
                {"entity_id": "banana", "semantic_name": "banana", "category": "fruit"},
            ], "asset_choices": [], "relations": [], "operations": operations,
        },
        "scene_query": None, "session_control": None,
        "robot_setup_request": None, "robot_asset_switch": None,
        "entities": [], "operations": [], "relations": [],
    }


def test_multi_clause_regions_are_not_broadcast():
    operations = [
        {"operation": "add", "target": "apple", "relation": "on", "reference": "table",
         "placement_hint": "any", "placement_region": "left_front"},
        {"operation": "add", "target": "banana", "relation": "on", "reference": "table",
         "placement_hint": "any", "placement_region": "right_back"},
    ]
    turn = parse_qwen_turn(_envelope(operations), "在桌面左上角增加苹果，在桌面右下角增加香蕉")
    assert [item.placement_region for item in turn.scene_edit.operations] == ["left_front", "right_back"]


def test_object_relative_relation_is_not_rewritten_to_table():
    operations = [{"operation": "add", "target": "banana", "relation": "right_of",
                   "reference": "apple", "placement_hint": None, "placement_region": None}]
    turn = parse_qwen_turn(_envelope(operations), "在苹果右边增加香蕉")
    op = turn.scene_edit.operations[0]
    assert op.relation == "right_of" and op.reference == "apple"


def test_live_catalog_response_without_protocol_is_rejected():
    snapshot = AssetCatalogSnapshot.from_items(
        [CatalogAsset(asset_key="model:1", name="apple", selectable_for_add=True)], [],
    )
    value = _envelope([{"operation": "add", "target": "apple", "relation": "on",
                        "reference": "table", "placement_hint": "any", "placement_region": None}])
    value.pop("protocol_version")
    request = TaskUnderstandingRequest(instruction="增加苹果", asset_catalog=snapshot)
    try:
        QwenHTTPProvider._validate_live_asset_choices(value, request)
    except QwenProviderError as exc:
        assert exc.code == "provider_output_schema_invalid"
    else:
        raise AssertionError("missing live protocol must not use replay compatibility")
