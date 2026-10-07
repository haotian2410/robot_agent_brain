from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.contracts.camera import CameraRequest
from robot_agent_brain.contracts.scene import PatchAction, SceneConfig, SceneObject, ScenePatch, ScenePatchOperation, Transform
from robot_agent_brain.contracts.scene import ModelProperty
from robot_agent_brain.contracts.task_intent import PlacementTarget
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from support_fixtures import add_table


def base_scene():
    return SceneConfig(scene_id="scene-001", scene_version=0, robot="ur5e", objects=[
        SceneObject(scene_object_id="apple_01", asset_id="apple_basic", semantic_name="apple", category="fruit"),
    ])


def test_scene_patch_add_and_update_are_versioned():
    platform = MockScenePlatform()
    platform.load_scene(base_scene())
    snapshot = platform.apply_patch(ScenePatch(
        scene_id="scene-001", base_scene_version=0, operations=[ScenePatchOperation(
            action=PatchAction.ADD,
            scene_object_id="box_01",
            object=SceneObject(scene_object_id="box_01", asset_id="box_basic", semantic_name="box", category="container"),
        )],
    ))
    assert snapshot.scene_version == 1
    assert platform.manager.scene.objects[-1].scene_object_id == "box_01"

    platform.apply_patch(ScenePatch(
        scene_id="scene-001", base_scene_version=1, operations=[ScenePatchOperation(
            action=PatchAction.UPDATE_TRANSFORM,
            scene_object_id="apple_01",
            transform=Transform(position=(0.1, 0.2, 0.0)),
        )],
    ))
    assert platform.manager.scene.objects[0].transform.position == (0.1, 0.2, 0.0)


def test_camera_request_returns_mock_frame_with_scene_version():
    platform = MockScenePlatform(rgb=b"rgb")
    platform.load_scene(base_scene())
    frame = platform.capture(CameraRequest(width=640, height=480))
    assert frame.scene_id == "scene-001"
    assert frame.scene_version == 0
    assert frame.rgb == b"rgb"


def test_scene_editor_computes_initial_layout_but_not_robot_placement():
    scene = base_scene()
    assets = LocalAssetCatalog([
        ModelProperty(asset_id="apple_basic", semantic_name="apple", category="fruit", dimensions_m=(0.08, 0.08, 0.09)),
        ModelProperty(asset_id="box_basic", semantic_name="box", category="container", dimensions_m=(0.30, 0.25, 0.12)),
    ])
    add_table(scene, assets)
    patch = SceneEditor(assets).add_object(
        scene, "box_01", "box_basic", "box", "container",
        relation=PlacementTarget(kind="relative_object", reference="apple_01", relation="right_of"),
        reference_object=scene.objects[0],
    )
    assert patch.operations[0].object.transform.position[0] > 0
