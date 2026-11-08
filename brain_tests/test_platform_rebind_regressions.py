"""Real repository-class regressions for the platform rebind safety plan.

These tests deliberately use the production OLS adapter and BrainSession.  The
platform is only an in-memory acknowledgement boundary; no Control or robot
execution is involved.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from robot_agent_brain.adapters.final_models_library import FinalModelsLibraryAdapter
from robot_agent_brain.adapters.ols_robot_assembly import OlsRobotAssemblyAdapter
from robot_agent_brain.contracts.scene import SceneConfig, SceneSnapshot
from robot_agent_brain.session.brain_session import BrainSession


OLS_DATA = Path("/home/cscvlab/lht/webeditor_runtime/ObjectLibraryServer-1.0.8-rel/data")


class RecordingPlatform:
    def __init__(self):
        self.scene = None
        self.calls = []
        self.next_object_id = 0

    def load_scene(self, scene, *, change_kind="scene_edit"):
        self.calls.append((change_kind, scene))
        self.scene = scene
        self.next_object_id = max((item.object_id_in_scene for item in scene.objects), default=-1) + 1
        return SceneSnapshot(scene_id=scene.scene_id, scene_version=scene.scene_version,
                             scene_sub_version=scene.scene_sub_version)

    def adopt(self, scene):
        return self.load_scene(scene, change_kind="adopt")


@pytest.fixture
def scene_adapter():
    if not OLS_DATA.is_dir():
        pytest.skip("OLS 1.0.8 runtime assets are not installed")
    adapter = OlsRobotAssemblyAdapter(FinalModelsLibraryAdapter(OLS_DATA))
    scene = SceneConfig.model_validate_json((OLS_DATA / "scenes/1/ur5e_table_empty.json").read_text())
    # The real scene has deployment positions but no live-now field.  Keep a
    # non-zero now value in the fixture so a camera/gripper-only change cannot
    # accidentally reset runtime evidence.
    payload = scene.raw_document()
    for obj in payload["objects"]:
        for component in obj["components"]:
            if component["component_type"] == "RobotDriver" and obj["object_id_in_scene"] == 2:
                component["properties"]["now_joint_positions_rad"] = {
                    "shoulder_pan_joint": 0.31, "shoulder_lift_joint": -1.2,
                    "elbow_joint": 0.77, "wrist_1_joint": -0.6,
                    "wrist_2_joint": -1.1, "wrist_3_joint": 0.2,
                }
    return SceneConfig.model_validate(payload), adapter


def _object(scene, object_id):
    return next(item for item in scene.objects if item.object_id_in_scene == object_id)


def _component(obj, kind):
    return next(item for item in obj.components if item.component_type == kind)


def test_camera_only_preserves_arm_driver_and_unknown_components(scene_adapter):
    scene, adapter = scene_adapter
    candidate, binding = adapter.rebind_scene(scene, camera_asset="d455")
    assert binding["changed_roles"] == ["camera"]
    assert _object(candidate, 2).model_dump(mode="json") == _object(scene, 2).model_dump(mode="json")
    assert _object(candidate, 3).model_dump(mode="json") == _object(scene, 3).model_dump(mode="json")
    assert candidate.scene_sub_version == scene.scene_sub_version + 1


def test_gripper_only_preserves_arm_driver_and_pose(scene_adapter):
    scene, adapter = scene_adapter
    candidate, binding = adapter.rebind_scene(scene, gripper_asset="robotiq_2f140")
    assert binding["changed_roles"] == ["gripper"]
    assert _object(candidate, 2).model_dump(mode="json") == _object(scene, 2).model_dump(mode="json")
    assert _component(_object(candidate, 3), "RobotAttachment").properties["parent_object_id"] == 2


def test_arm_switch_rebinds_existing_gripper_without_inventing_mount_pose(scene_adapter):
    scene, adapter = scene_adapter
    before = _component(_object(scene, 3), "RobotAttachment").properties["transform"]
    candidate, _ = adapter.rebind_scene(scene, robot_asset="piper")
    attachment = _component(_object(candidate, 3), "RobotAttachment").properties
    assert attachment["parent_joint"] == "joint6"
    assert attachment["parent_link"] == "link6"
    assert attachment["transform"] == before


def test_same_asset_rebind_is_a_true_noop(scene_adapter):
    scene, adapter = scene_adapter
    candidate, binding = adapter.rebind_scene(scene, robot_asset="ur5e_arm")
    assert binding["noop"] is True
    assert candidate.model_dump(mode="json") == scene.model_dump(mode="json")


def test_rebind_session_requires_exact_platform_scope(scene_adapter):
    scene, adapter = scene_adapter
    platform = RecordingPlatform()
    session = BrainSession(scene, SimpleNamespace(robot="ur5e"), platform)
    session.robot_assembly_adapter = adapter
    session.platform_object_ids = {item.object_id_in_scene for item in scene.objects}
    candidate, _ = adapter.rebind_scene(scene, camera_asset="d455")
    # A platform rebind may not smuggle a normal object edit through the same
    # change kind.  This uses a deliberate ordinary-table transform change.
    payload = candidate.raw_document()
    for obj in payload["objects"]:
        if obj["object_id_in_scene"] == 1:
            for component in obj["components"]:
                if component["component_type"] == "Transform":
                    component["properties"]["position"][0] += 0.1
    invalid = SceneConfig.model_validate(payload)
    with pytest.raises(ValueError, match="platform_rebind"):
        session.accept_browser_scene(invalid, platform_object_ids=session.platform_object_ids,
                                     change_kind="platform_rebind")
    assert len(platform.calls) == 1  # only the initial session import


def test_platform_scope_does_not_trust_candidate_robot_category(scene_adapter):
    scene, adapter = scene_adapter
    platform = RecordingPlatform()
    session = BrainSession(scene, SimpleNamespace(robot="ur5e"), platform)
    session.robot_assembly_adapter = adapter
    session.platform_object_ids = {2, 3, 4, 5, 6}
    candidate, _ = adapter.rebind_scene(scene, camera_asset="d455")
    payload = candidate.raw_document()
    for obj in payload["objects"]:
        if obj["object_id_in_scene"] == 1:
            for component in obj["components"]:
                if component["component_type"] == "MetadataRef":
                    component["properties"] = {"path": "$LIBRARY_SERVER/8", "type": "robot"}
    invalid = SceneConfig.model_validate(payload)
    with pytest.raises(ValueError, match="platform_rebind_scope_invalid"):
        session.accept_browser_scene(invalid, platform_object_ids=session.platform_object_ids,
                                     change_kind="platform_rebind")


def test_current_agent_owner_may_rebind_while_agent_owned(scene_adapter):
    scene, adapter = scene_adapter
    platform = RecordingPlatform()
    session = BrainSession(scene, SimpleNamespace(robot="ur5e"), platform)
    session.robot_assembly_adapter = adapter
    session.platform_object_ids = {2, 3, 4, 5, 6}
    session.session_phase = "agent_owned"
    session.active_task_owner = 101
    request = SimpleNamespace(robot_asset="piper", gripper_asset=None, camera_asset=None)
    binding = session.rebind_platform_assets(adapter, request, owner_task_id=101)
    assert binding["robot_asset"] == "piper"
    assert session.scene.scene_sub_version == scene.scene_sub_version + 1


def test_foreign_agent_owner_cannot_rebind_while_agent_owned(scene_adapter):
    scene, adapter = scene_adapter
    platform = RecordingPlatform()
    session = BrainSession(scene, SimpleNamespace(robot="ur5e"), platform)
    session.robot_assembly_adapter = adapter
    session.platform_object_ids = {2, 3, 4, 5, 6}
    session.session_phase = "agent_owned"
    session.active_task_owner = 101
    with pytest.raises(ValueError, match="platform_rebind_task_busy"):
        session.rebind_platform_assets(adapter, SimpleNamespace(robot_asset="piper", gripper_asset=None, camera_asset=None))


def test_reintroduced_pedestal_uses_session_highwater_not_retired_id(scene_adapter):
    scene, adapter = scene_adapter
    platform = RecordingPlatform()
    session = BrainSession(scene, SimpleNamespace(robot="ur5e"), platform)
    session.robot_assembly_adapter = adapter
    session.platform_object_ids = {2, 3, 4, 5, 6}
    session.next_scene_object_id = 20  # IDs 0..19 are historical/retired.
    first = session.rebind_platform_assets(adapter, SimpleNamespace(robot_asset="piper", gripper_asset=None, camera_asset=None))
    assert first["robot_asset"] == "piper"
    assert 6 not in {o.object_id_in_scene for o in session.scene.objects}
    session.next_scene_object_id = max(session.next_scene_object_id, 20)
    second = session.rebind_platform_assets(adapter, SimpleNamespace(robot_asset="ur5e_arm", gripper_asset=None, camera_asset=None), owner_task_id=None)
    # The old pedestal id must not be recycled after the Piper branch removed it.
    ids = {o.object_id_in_scene for o in session.scene.objects}
    assert 6 not in ids
    assert max(ids) >= 20


def test_first_turn_platform_switch_publishes_final_candidate_once(tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    from robot_agent_brain.contracts.robot_setup import RobotAssetSwitchRequest
    from robot_agent_brain.contracts.turn import BrainTurn

    if not OLS_DATA.is_dir():
        pytest.skip("OLS 1.0.8 runtime assets are not installed")

    class Provider:
        def understand_turn(self, _request):
            return BrainTurn(status="accepted", turn_kind="robot_config", instruction="换成 Piper",
                             robot_asset_switch=RobotAssetSwitchRequest(robot_asset="piper"))

    platforms = []
    def factory():
        value = RecordingPlatform()
        platforms.append(value)
        return value

    config = BrainConfig.load(Path("config/webeditor.json")).model_copy(
        update={"vision": False, "output_dir": str(tmp_path), "asset_geometry_cache": None})
    try:
        app = BrainApplication(config, provider=Provider(), platform_factory=factory)
    except ValueError as exc:
        if str(exc).startswith("asset_geometry_cache_"):
            pytest.skip(f"external OLS/cache unavailable: {exc}")
        raise
    report = app.handle("换成 Piper")
    assert report.run_status == "success"
    assert report.scene_commit_status == "committed"
    assert len(platforms) == 1
    assert len(platforms[0].calls) == 1
    published = platforms[0].calls[0][1]
    assert published.scene_version == 1 and published.scene_sub_version == 0
    assert any("piper" in str(c.properties).casefold() for o in published.objects for c in o.components)
