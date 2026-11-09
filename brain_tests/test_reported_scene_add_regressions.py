import unittest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.turn import SceneEditPlan
from robot_agent_brain.models.task_understanding import _normalize_scene_edit_layout_output
from robot_agent_brain.scene.bootstrapper import make_object
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.scene_graph import world_transform


class ReportedSceneAddTests(unittest.TestCase):
    def plan(self, **fields):
        return SceneEditPlan(entities=[dict(entity_id="fruit", semantic_name="banana", category="fruit")],
            operations=[dict(operation="add", target="fruit", relation="on", reference="table", **fields)])

    def scene(self):
        return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="test",
            objects=[make_object(0, "table", "$DEMO_LIBRARY/1", (0, 0, -.025), category="surface")])

    def test_explicit_words_override_conflicting_provider_region(self):
        for instruction, wrong, expected, hint in [
            ("在桌子右上角生成一个苹果", "right_back", "right_front", "any"),
            ("在桌面正中央生成一个苹果", "front_half", None, "center"),
        ]:
            value = {"scene_edit": self.plan(placement_region=wrong, placement_hint="any").model_dump()}
            normalized = _normalize_scene_edit_layout_output(value, instruction)
            op = normalized["scene_edit"]["operations"][0]
            self.assertEqual(op["placement_region"], expected)
            self.assertEqual(op["placement_hint"], hint)

    def test_add_color_and_occupied_exact_center_are_atomic(self):
        scene = self.scene()
        editor = SceneEditor(BrainConfig().load_assets())
        patch = editor.edit(self.plan(properties={"color": "blue"}, placement_hint="center"), scene)
        final = SceneManager(scene).apply_patch(patch)
        obj = final.objects[-1]
        self.assertEqual(SceneIndex(final).component(obj.object_id_in_scene, "MeshRenderer").properties["forceOverrideColor"], "#0000FF")
        self.assertEqual(world_transform(final, obj.object_id_in_scene).position[:2], (0, 0))
        before = final.model_dump()
        with self.assertRaisesRegex(ValueError, "collision"):
            editor.edit(self.plan(placement_hint="center"), final)
        self.assertEqual(final.model_dump(), before)
        with self.assertRaisesRegex(ValueError, "properties_unsupported"):
            editor.edit(self.plan(properties={"mass": 10}), scene)
        with self.assertRaisesRegex(ValueError, "color_unknown"):
            editor.edit(self.plan(properties={"color": "unknown"}), scene)

    def test_right_upper_uses_positive_x_and_y(self):
        scene = self.scene()
        editor = SceneEditor(BrainConfig().load_assets())
        plan = self.plan(placement_region="right_front")
        final = SceneManager(scene).apply_patch(editor.edit(plan, scene))
        position = world_transform(final, final.objects[-1].object_id_in_scene).position
        self.assertGreater(position[0], 0)
        self.assertGreater(position[1], 0)

    def test_multiple_operations_keep_their_own_regions(self):
        plan = self.plan(placement_region="right_back").model_dump()
        plan["operations"] *= 2
        value = {"scene_edit": plan}
        self.assertEqual(_normalize_scene_edit_layout_output(value, "在桌子右上角生成苹果，左下角生成香蕉"), value)

    def test_local_microwave_is_addable_but_robot_is_not(self):
        config = BrainConfig.load("config/webeditor_local.json")
        # Read authoritative OLS metadata independently of a derived cache.
        config = config.model_copy(update={"asset_geometry_cache": None})
        snapshot = config.load_assets().catalog_snapshot()
        microwave = next(item for item in snapshot.models if item.name == "microwave")
        self.assertTrue(microwave.selectable_for_add)
        self.assertEqual(microwave.availability_reason, "passive_scene_model")
        self.assertTrue(all(not item.selectable_for_add for item in snapshot.robots))


if __name__ == "__main__":
    unittest.main()
