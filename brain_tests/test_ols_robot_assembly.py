from pathlib import Path
from types import SimpleNamespace

import pytest

from robot_agent_brain.adapters.final_models_library import FinalModelsLibraryAdapter
from robot_agent_brain.adapters.ols_robot_assembly import OlsRobotAssemblyAdapter
from robot_agent_brain.contracts.scene import SceneConfig, SceneSnapshot
from robot_agent_brain.session.brain_session import BrainSession


OLS_DATA = Path("/home/cscvlab/lht/webeditor_runtime/ObjectLibraryServer-1.0.8-rel/data")


class _Platform:
    def __init__(self):
        self.scene = None
        self.next_object_id = 0

    def load_scene(self, scene, *, change_kind="scene_edit"):
        self.scene = scene
        self.next_object_id = max((item.object_id_in_scene for item in scene.objects), default=-1) + 1
        return SceneSnapshot(scene_id=scene.scene_id, scene_version=scene.scene_version,
                             scene_sub_version=scene.scene_sub_version)

    def adopt(self, scene):
        return self.load_scene(scene)


@pytest.fixture
def adapter():
    if not OLS_DATA.is_dir():
        pytest.skip("OLS 1.0.8 runtime assets are not installed")
    return OlsRobotAssemblyAdapter(FinalModelsLibraryAdapter(OLS_DATA))


def test_ols_catalog_classifies_arm_gripper_and_camera(adapter):
    catalog = {item["semantic_name"]: item for item in adapter.catalog()}
    assert catalog["ur5e_arm"]["role"] == "arm"
    assert catalog["piper"]["role"] == "arm"
    assert catalog["robotiq_2f140"]["role"] == "gripper"
    assert catalog["d455"]["role"] == "camera"


def test_platform_rebind_preserves_ids_and_increments_only_subversion(adapter):
    scene = SceneConfig.model_validate_json((OLS_DATA / "scenes/1/ur5e_table_empty.json").read_text())
    platform = _Platform()
    session = BrainSession(scene, SimpleNamespace(robot="ur5e"), platform)
    session.robot_assembly_adapter = adapter
    session.platform_object_ids = {item.object_id_in_scene for item in scene.objects}
    candidate, binding = adapter.rebind_scene(
        scene, robot_asset="piper", gripper_asset="robotiq_2f140", camera_asset="d455"
    )

    assert session.accept_browser_scene(
        candidate, platform_object_ids=session.platform_object_ids, change_kind="platform_rebind"
    ) is True
    assert session.scene.scene_id == scene.scene_id
    assert session.scene.scene_version == scene.scene_version
    assert session.scene.scene_sub_version == scene.scene_sub_version + 1
    assert {item.object_id_in_scene for item in session.scene.objects} == {
        item.object_id_in_scene for item in scene.objects
    } - {6}  # Piper's OLS scene_one_arm declares no pedestal
    assert (session.robot_asset, session.gripper_asset, session.camera_asset) == (
        "piper", "robotiq_2f140", "d455"
    )
    assert session.execution_capability == "unsupported"
    assert 6 not in session.platform_object_ids  # Piper has no pedestal in OLS 1.0.8
    assert binding["asset_revision"]


def test_normal_scene_edit_cannot_replace_platform_metadata(adapter):
    scene = SceneConfig.model_validate_json((OLS_DATA / "scenes/1/ur5e_table_empty.json").read_text())
    candidate, _ = adapter.rebind_scene(scene, robot_asset="piper")
    platform = _Platform()
    session = BrainSession(scene, SimpleNamespace(robot="ur5e"), platform)
    session.robot_assembly_adapter = adapter
    session.platform_object_ids = {item.object_id_in_scene for item in scene.objects}
    with pytest.raises(ValueError, match="scene_platform_manifest_invalid"):
        session.accept_browser_scene(candidate, platform_object_ids=session.platform_object_ids,
                                     change_kind="scene_edit")


def test_camera_only_rebind_does_not_reposition_arm_or_remove_pedestal(adapter):
    scene = SceneConfig.model_validate_json((OLS_DATA / "scenes/1/ur5e_table_empty.json").read_text())
    candidate, _ = adapter.rebind_scene(scene, camera_asset="d455")
    before = {item.object_id_in_scene: item for item in scene.objects}
    after = {item.object_id_in_scene: item for item in candidate.objects}
    assert after.keys() == before.keys()
    assert next(item for item in after[2].components if item.component_type == "Transform").model_dump(mode="json") == next(item for item in before[2].components if item.component_type == "Transform").model_dump(mode="json")
    assert next(item for item in after[6].components if item.component_type == "MetadataRef").properties["path"] == "$LIBRARY_SERVER/4"
