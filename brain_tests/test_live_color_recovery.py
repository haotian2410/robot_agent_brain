import json
import unittest

import httpx

from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest


class LiveColorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.catalog = AssetCatalogSnapshot.from_items(
            [CatalogAsset(asset_key="model:1", name="apple", aliases=("苹果",),
                          category="fruit", selectable_for_add=True)], [],
        )

    def understand(self, value, instruction):
        def handler(_request):
            content = json.dumps(value, ensure_ascii=False)
            return httpx.Response(200, json={"choices": [{"message": {"content": content},
                                                            "finish_reason": "stop"}]})
        provider = QwenHTTPProvider("http://example/v1", "test-model",
                                    transport=httpx.MockTransport(handler))
        return provider.understand_turn(TaskUnderstandingRequest(
            instruction=instruction, asset_catalog=self.catalog))

    def test_color_add_clarification_uses_unique_model_with_override(self):
        instruction = "在桌面上生成一个黄色的苹果"
        value = {"protocol_version": "task_understanding.v3.1",
                 "status": "clarification_required", "turn_kind": "scene_edit",
                 "clarification_question": "目录里没有黄色苹果。", "scene_edit": None,
                 "scene_query": None, "session_control": None, "robot_setup_request": None,
                 "robot_asset_switch": None, "robot_asset": None, "gripper_asset": None,
                 "camera_asset": None, "profile_id": None, "entities": [],
                 "operations": [], "relations": []}
        turn = self.understand(value, instruction)
        self.assertEqual(turn.status.value, "accepted")
        operation = turn.scene_edit.operations[0]
        self.assertEqual(operation.properties, {"color": "yellow"})
        self.assertEqual(turn.scene_edit.asset_choices[0].asset_key, "model:1")

    def test_live_edit_count_becomes_a_stable_subset_request(self):
        instruction = "删除三个苹果"
        value = {"protocol_version": "task_understanding.v3.1", "status": "accepted",
                 "turn_kind": "scene_edit", "scene_edit": {
                     "entities": [{"entity_id": "apples", "semantic_name": "apple",
                                   "category": "fruit", "count": 3,
                                   "quantity_mode": "candidate_pool", "all_available": False}],
                     "relations": [],
                     "operations": [{"operation": "remove", "target": "apples"}],
                 }}
        turn = self.understand(value, instruction)
        entity = turn.scene_edit.entities[0]
        self.assertEqual(entity.count, 3)
        self.assertEqual(entity.quantity_mode.value, "all")
        self.assertFalse(entity.all_available)
        self.assertTrue(entity.select_count_from_candidates)

    def test_live_all_scope_is_preserved_for_bulk_edits(self):
        instruction = "删除所有苹果"
        value = {"protocol_version": "task_understanding.v3.1", "status": "accepted",
                 "turn_kind": "scene_edit", "scene_edit": {
                     "entities": [{"entity_id": "apples", "semantic_name": "apple",
                                   "category": "fruit", "count": 1,
                                   "quantity_mode": "single", "all_available": False}],
                     "relations": [],
                     "operations": [{"operation": "remove", "target": "apples"}],
                 }}
        turn = self.understand(value, instruction)
        entity = turn.scene_edit.entities[0]
        self.assertEqual(entity.quantity_mode.value, "all")
        self.assertTrue(entity.all_available)

    def test_color_update_drops_only_unreferenced_near_and_selects_source_color(self):
        for instruction, source, destination in (
            ("把红色的苹果改成绿色", "red", "green"),
            ("把绿色的苹果改成红色", "green", "red"),
        ):
            with self.subTest(instruction=instruction):
                value = {"protocol_version": "task_understanding.v3.1", "status": "accepted",
                         "turn_kind": "scene_edit", "scene_edit": {
                             "scene_basis": "current",
                             "entities": [{"entity_id": f"{source}_apple", "semantic_name": "apple",
                                           "category": "fruit"}],
                             "relations": [{"scope": "selection", "subject": f"{source}_apple",
                                            "relation": "near", "reference": None}],
                             "operations": [{"operation": "update_properties", "target": f"{source}_apple",
                                             "properties": {"color": destination}}],
                         }}
                turn = self.understand(value, instruction)
                self.assertEqual(turn.scene_edit.entities[0].color, source)
                self.assertEqual(turn.scene_edit.relations, [])
                self.assertEqual(turn.scene_edit.operations[0].properties, {"color": destination})

    def test_color_update_does_not_repair_without_matching_explicit_color(self):
        instruction = "把苹果改成绿色"
        value = {"status": "accepted", "scene_edit": {
            "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "relations": [{"subject": "apple", "relation": "near", "reference": None}],
            "operations": [{"operation": "update_properties", "target": "apple",
                            "properties": {"color": "green"}}],
        }}
        with self.assertRaisesRegex(QwenProviderError, "near requires reference"):
            self.understand(value, instruction)

    def test_unreferenced_near_is_not_removed_for_other_object_color(self):
        instruction = "把红色苹果旁边的香蕉改成绿色"
        value = {"status": "accepted", "scene_edit": {
            "entities": [{"entity_id": "banana", "semantic_name": "banana", "category": "fruit"}],
            "relations": [{"subject": "banana", "relation": "near", "reference": None}],
            "operations": [{"operation": "update_properties", "target": "banana",
                            "properties": {"color": "green"}}],
        }}
        with self.assertRaisesRegex(QwenProviderError, "near requires reference"):
            self.understand(value, instruction)

    def test_add_recovery_does_not_override_non_catalog_clarification(self):
        instruction = "在桌面中央生成一个黄色的苹果"
        value = {"protocol_version": "task_understanding.v3.1",
                 "status": "clarification_required", "turn_kind": "scene_edit",
                 "clarification_question": "桌面中央已被占用，请指定其它位置。",
                 "scene_edit": None, "scene_query": None, "session_control": None,
                 "robot_setup_request": None, "robot_asset_switch": None, "robot_asset": None,
                 "gripper_asset": None, "camera_asset": None, "profile_id": None,
                 "entities": [], "operations": [], "relations": []}
        turn = self.understand(value, instruction)
        self.assertEqual(turn.status.value, "clarification_required")


if __name__ == "__main__":
    unittest.main()
