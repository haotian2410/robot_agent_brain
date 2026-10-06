import json
import pytest
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.camera import CameraRequest


def test_empty_scene_is_valid_and_input_bytes_unchanged(tmp_path):
    path = tmp_path / "scene.json"
    data = SceneConfig(scene_id="empty").model_dump_json(indent=2)
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


def test_unknown_asset_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version":"1.0","scene_id":"s","objects":[
        {"scene_object_id":"x","asset_id":"unknown","semantic_name":"apple","category":"fruit"}]}))
    with pytest.raises(ValueError, match="scene_file_invalid"):
        SceneFileCodec(BrainConfig().load_assets()).load(path)


def test_local_platform_never_supplies_mock_rgb():
    platform = LocalScenePlatform()
    assert platform.load_scene(SceneConfig(scene_id="s")).accepted
    with pytest.raises(ValueError, match="vision_unavailable"):
        platform.capture(CameraRequest())
