from types import SimpleNamespace

import pytest

from robot_agent_brain.contracts.scene import SceneComponent
from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest
from test_component_runtime import object_
from test_web_service import configured


def platform_fixture(tmp_path, monkeypatch):
    service, browser = configured(tmp_path)
    template = browser.scene.model_copy(deep=True)
    arm = object_(3, metadata_ref="$LIBRARY_SERVER/1")
    arm.components[1].properties["type"] = "robot"
    arm.components.append(SceneComponent(component_type="RobotDriver", properties={
        "joint_sequence": ["joint6"], "joint_limits": {"joint6": [-2, 2]},
    }))
    template.objects.append(arm)
    service.app.bootstrapper.template_scene = template
    service.config.scene_platform_object_ids = {0, 3}
    monkeypatch.setattr(service.app.robot_assembly, "catalog", lambda: [
        {"asset_key": "robot:1"}, {"asset_key": "robot:8"},
    ])
    current = template.model_copy(deep=True)
    current.objects[-1].object_id_in_scene = 30
    current.objects[-1].components[1].properties["path"] = "$LIBRARY_SERVER/8"
    current.objects[-1].components[-1].properties.update(
        available_connect_link=["link6"], position=[[0, 0, 0]], quaternion_xyzw=[[0, 0, 0, 1]])
    current.objects.append(object_(31, "banana", metadata_ref="$DEMO_LIBRARY/3"))
    return service, browser, template, current


def test_new_session_accepts_catalog_platform_and_rebuilds_manifest(tmp_path, monkeypatch):
    service, browser, template, current = platform_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(service.app.robot_assembly, "classify_scene", lambda scene: {"arm": [(30, None)]})
    monkeypatch.setattr(service.app.robot_assembly, "scene_binding", lambda scene: {
        "robot_asset": "piper", "gripper_asset": None, "camera_asset": None})
    try:
        validated = service.validate_scene(current)
        assert service._initial_platform(validated)[1] == {0, 30}
        identifier = service.activate(SessionRequest(browserID="b", scene=current.model_dump(mode="json")))["sessionID"]
        browser.scene = validated
        request = StartTask(command="把苹果向右移动10厘米", scene=validated, sceneDigest=digest(validated),
                            browserID="b", sessionID=identifier, clientRequestID="after-piper")
        record, fresh = service.tasks.submit(request)
        assert fresh
        service.execute(record["id"])
        result = service.tasks.get(record["id"])["result"]
        assert result["outcome"] == "scene_updated", result.get("error", result.get("reply"))
        session = service.app.get_session(identifier)
        assert session.platform_object_ids == {0, 30}
        assert session.robot_asset == "piper"
        assert session.execution_capability == "unsupported"
        from test_application_artifacts import robot
        with pytest.raises(ValueError, match="capability_unsupported"):
            session.check_turn(robot())
        assert next(o for o in session.scene.objects if o.object_id_in_scene == 30) == current.objects[-2]
        assert next(o for o in session.scene.objects if o.object_id_in_scene == 31) == current.objects[-1]
    finally:
        service.tasks.close()


def test_initialized_session_still_rejects_platform_change(tmp_path, monkeypatch):
    service, _, template, current = platform_fixture(tmp_path, monkeypatch)
    try:
        session = SimpleNamespace(scene=template, platform_object_ids={0, 3})
        with pytest.raises(ValueError, match="web_platform_profile_unsupported"):
            service.validate_scene(current, session)
    finally:
        service.tasks.close()


@pytest.mark.parametrize("mutation", ["unknown_robot", "replace_table"])
def test_new_session_rejects_unknown_asset_or_replaced_infrastructure(tmp_path, monkeypatch, mutation):
    service, _, _, current = platform_fixture(tmp_path, monkeypatch)
    try:
        if mutation == "unknown_robot":
            current.objects[-2].components[1].properties["path"] = "$LIBRARY_SERVER/999"
        else:
            metadata = next(c for c in current.objects[0].components if c.component_type == "MetadataRef")
            metadata.properties.update(path="$LIBRARY_SERVER/8", type="robot")
        with pytest.raises(ValueError, match="web_platform_profile_unsupported"):
            service.validate_scene(current)
    finally:
        service.tasks.close()
