import json
import pytest
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.camera import CameraRequest
from test_component_runtime import object_


def test_empty_scene_is_valid_and_input_bytes_unchanged(tmp_path):
    path = tmp_path / "scene.json"
    data = SceneConfig(scene_schema_version=1, scene_version=1, scene_id=0, scene_name="empty", objects=[]).model_dump_json(indent=2)
    path.write_text(data)
    result = SceneFileCodec(BrainConfig().load_assets()).load(path)
    assert result.objects == []
    assert path.read_text() == data


@pytest.mark.parametrize("data", ["broken", '{"schema_version":"2.0"}', '{"components":[]}',
    '{"schema_version":"1.0","scene_id":"s","scene_version":NaN}'])
def test_invalid_input_not_silently_generated(tmp_path, data):
    path = tmp_path / "bad.json"
    path.write_text(data)
    with pytest.raises(ValueError, match="scene_(file_invalid|schema_unsupported)"):
        SceneFileCodec(BrainConfig().load_assets()).load(path)
    assert path.read_text() == data


def test_unknown_asset_deferred_until_resource_resolution(tmp_path):
    path = tmp_path / "scene.json"
    scene = SceneConfig(scene_schema_version=1, scene_version=1, scene_id=0, scene_name="unresolved",
                        objects=[object_(0, "apple", metadata_ref="$LIBRARY_SERVER/999")])
    path.write_text(scene.model_dump_json())
    assets = BrainConfig().load_assets()
    assert SceneFileCodec(assets).load(path) == scene
    with pytest.raises(LookupError, match="asset_missing"):
        assets.resolve("$LIBRARY_SERVER/999")


def test_local_platform_never_supplies_mock_rgb():
    platform = LocalScenePlatform()
    assert platform.load_scene(SceneConfig(scene_schema_version=1, scene_version=1, scene_id=0, scene_name="s", objects=[])).accepted
    with pytest.raises(ValueError, match="vision_unavailable"):
        platform.capture(CameraRequest())
