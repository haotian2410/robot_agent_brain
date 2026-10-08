from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.camera import CameraRequest
from robot_agent_brain.contracts.scene import SceneConfig, ScenePatch, ScenePatchOperation
from robot_agent_brain.contracts.turn import SceneEditPlan, SceneEditIntent
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.component_access import SceneIndex
from test_component_runtime import object_
from test_query_scene_continuity import supported_scene


def base_scene():
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="scene-001",
                       objects=[object_(0, "apple", metadata_ref="$DEMO_LIBRARY/2")])


def test_scene_patch_add_and_update_are_versioned():
    platform = MockScenePlatform()
    platform.load_scene(base_scene())
    snapshot = platform.apply_patch(ScenePatch(scene_id=1, base_scene_version=0, operations=[
        ScenePatchOperation(action="add_object", object_id_in_scene=1,
                            object=object_(1, "box", "container", metadata_ref="$DEMO_LIBRARY/5"))]))
    assert snapshot.scene_version == 1
    assert platform.manager.scene.objects[-1].object_id_in_scene == 1
    platform.apply_patch(ScenePatch(scene_id=1, base_scene_version=1, operations=[
        ScenePatchOperation(action="upsert_component", object_id_in_scene=0,
                            component=object_(0, position=(.1,.2,0)).components[0])]))
    assert SceneIndex(platform.manager.scene).transform(0).position == (.1, .2, 0)


def test_camera_request_returns_mock_frame_with_scene_version():
    platform = MockScenePlatform(rgb=b"rgb")
    platform.load_scene(base_scene())
    frame = platform.capture(CameraRequest(width=640, height=480))
    assert frame.scene_id == 1
    assert frame.scene_version == 0
    assert frame.rgb == b"rgb"


def test_scene_editor_computes_initial_layout_but_not_robot_placement():
    scene = supported_scene()
    scene.objects.pop()
    before = scene.model_dump()
    patch = SceneEditor(BrainConfig().load_assets()).edit(SceneEditPlan(entities=[
        dict(entity_id="box", semantic_name="box", category="container"),
        dict(entity_id="apple", semantic_name="apple", category="fruit")],
        operations=[SceneEditIntent(operation="add", target="box", reference="apple", relation="right_of")]), scene)
    created = patch.operations[0].object
    assert created.components[0].properties["position"][0] > SceneIndex(scene).transform(1).position[0]
    assert scene.model_dump() == before
