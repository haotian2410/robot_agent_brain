import copy

import pytest

from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest, validate_web_scene
from robot_agent_brain.web.task_store import TaskStore
from test_query_scene_continuity import supported_scene
from test_web_service import configured


def _raw_scene():
    return supported_scene().model_dump(mode="json")


@pytest.mark.parametrize("mutate,code", [
    (lambda value: value["objects"][0].update(object_id_in_scene=2**32), "scene_object_id_invalid"),
    (lambda value: value["objects"].append(copy.deepcopy(value["objects"][0])), "scene_object_duplicate"),
    (lambda value: value["objects"][0]["components"].append(copy.deepcopy(value["objects"][0]["components"][0])), "scene_component_duplicate"),
    (lambda value: value["objects"][0]["components"].remove(next(c for c in value["objects"][0]["components"] if c["component_type"] == "Transform")), "scene_transform_missing"),
])
def test_web_scene_rejects_lossy_documents(mutate, code):
    raw = _raw_scene()
    mutate(raw)
    with pytest.raises(ValueError, match=code):
        validate_web_scene(raw)


def test_web_scene_rejects_malformed_transform_properties():
    raw = _raw_scene()
    transform = next(component for component in raw["objects"][0]["components"]
                     if component["component_type"] == "Transform")
    transform["properties"]["scale"] = [-1, 1, 1]
    with pytest.raises(ValueError, match="transform_scale_not_positive"):
        validate_web_scene(raw)


def test_invalid_activation_does_not_deactivate_current_session(tmp_path):
    service, _ = configured(tmp_path)
    current = service.activate(SessionRequest(browserID="b"))["sessionID"]
    bad = _raw_scene()
    bad["objects"][0]["components"] = []
    with pytest.raises(ValueError, match="scene_transform_missing"):
        service.activate(SessionRequest(browserID="b", scene=bad))
    assert service.tasks.binding(current)["active"] == 1
    service.tasks.close()


def test_existing_session_cannot_be_taken_by_another_browser(tmp_path):
    service, _ = configured(tmp_path)
    current = service.activate(SessionRequest(browserID="b"))["sessionID"]
    with pytest.raises(ValueError, match="session_browser_not_active"):
        service.activate(SessionRequest(browserID="other", sessionID=current))
    binding = service.tasks.binding(current)
    assert binding["active"] == 1 and binding["browser"] == "b"
    assert service.binding["id"] == current and service.binding["browser"] == "b"
    service.tasks.close()


def test_other_session_can_be_activated_while_first_session_has_task(tmp_path):
    service, browser = configured(tmp_path)
    first = service.activate(SessionRequest(browserID="b"))["sessionID"]
    request = StartTask(command="edit", scene=browser.scene, sessionID=first,
                        clientRequestID="running", browserID="b", sceneDigest=digest(browser.scene))
    record, fresh = service.tasks.submit(request)
    assert fresh and not service.tasks.get(record["id"])["terminal"]
    second = service.activate(SessionRequest(browserID="b"))["sessionID"]
    assert second != first and service.tasks.binding(second)["active"] == 1
    service.tasks.close()


def test_same_session_still_rejects_second_running_task(tmp_path):
    service, browser = configured(tmp_path)
    first = service.activate(SessionRequest(browserID="b"))["sessionID"]
    request = StartTask(command="edit", scene=browser.scene, sessionID=first,
                        clientRequestID="running", browserID="b", sceneDigest=digest(browser.scene))
    service.tasks.submit(request)
    with pytest.raises(ValueError, match="task_busy"):
        service.activate(SessionRequest(browserID="b", sessionID=first))
    service.tasks.close()


def test_rejected_busy_switch_restores_process_binding(tmp_path):
    service, browser = configured(tmp_path)
    first = service.activate(SessionRequest(browserID="b"))["sessionID"]
    # Create a second browser-owned session directly so the first remains the
    # service's active/process-local binding while the second has a task.
    second = service.tasks.activate("b")
    request = StartTask(command="edit", scene=browser.scene, sessionID=second,
                        clientRequestID="running", browserID="b", sceneDigest=digest(browser.scene))
    service.tasks.submit(request)
    with pytest.raises(ValueError, match="task_busy"):
        service.activate(SessionRequest(browserID="b", sessionID=second))
    assert service.binding["id"] == first
    service.tasks.close()


def test_activation_save_failure_rolls_back_new_session_cache_and_binding(tmp_path, monkeypatch):
    service, browser = configured(tmp_path)
    raw = browser.scene.model_dump(mode="json")
    raw["objects"].append({
        "object_id_in_scene": 9,
        "object_name_in_scene": "camera",
        "components": [
            {"component_type": "Transform", "properties": {
                "position": [0, 0, 1], "quaternion_xyzw": [0, 0, 0, 1],
                "scale": [1, 1, 1], "parent": None}},
            {"component_type": "Camera", "properties": {}},
        ],
    })
    def fail_save(_identifier):
        raise OSError("checkpoint write failed")
    monkeypatch.setattr(service.app, "_save_session", fail_save)
    with pytest.raises(OSError, match="checkpoint write failed"):
        service.activate(SessionRequest(browserID="b", scene=raw, camera_id=9))
    assert not [row for row in service.tasks.sessions() if row["active"]]
    assert not service.app.sessions
    assert service.binding is None
    service.tasks.close()
