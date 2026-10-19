import json
from pathlib import Path
import pytest

pytest.importorskip("rfc8785", reason="optional web integration dependencies not installed")
from robot_agent_brain.contracts.scene import SceneComponent, RobotDriverProperties
from robot_agent_brain.web.protocol import digest, validate_web_scene, StartTask
from robot_agent_brain.web.task_store import TaskStore
from test_query_scene_continuity import supported_scene


def task(scene=None):
    scene = scene or supported_scene()
    return StartTask(command="定位苹果",scene=scene,sessionID="s",clientRequestID="r",browserID="b",sceneDigest=digest(scene))


def test_empty_renderer_preserves_raw_properties():
    component = SceneComponent(component_type="MeshRenderer", properties={})
    assert component.model_dump()["properties"] == {}
    from robot_agent_brain.scene.colors import ColorEvidenceResolver
    from robot_agent_brain.scene.component_access import SceneIndex
    from robot_agent_brain.config import BrainConfig
    scene = supported_scene()
    scene.objects[1].components.append(component)
    from types import SimpleNamespace
    assets = SimpleNamespace(resolve=lambda *args: SimpleNamespace(color_tags=("red",),tags=()))
    assert ColorEvidenceResolver(assets).matches("red", scene.objects[1], SceneIndex(scene))


def test_fixed_connect_joint_and_now_are_distinct_from_deployment():
    driver = RobotDriverProperties(joint_sequence=["drive"], available_connect_joints=["fixed_mount"],
        now_joint_positions_rad={"drive":.2})
    assert "now_joint_positions_rad" not in driver.deployment_configuration()
    assert driver.available_connect_joints == ["fixed_mount"]
    for value in ({"unknown":0}, {"drive":float("nan")}):
        with pytest.raises(ValueError):
            RobotDriverProperties(joint_sequence=["drive"], available_connect_joints=[],now_joint_positions_rad=value)


def test_digest_is_cross_language_jcs_not_python_float_serialization():
    assert digest({"x":1.,"y":1e-6}) == digest({"y":.000001,"x":1})
    assert digest({"x":1}) != digest({"x":"1"})


def test_uint32_rejects_not_truncates():
    scene = supported_scene()
    scene.scene_id = 2**32
    with pytest.raises(ValueError, match="uint32"):
        validate_web_scene(scene)


def test_durable_tasks_idempotency_busy_restart(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    session = store.activate("b")
    request = task().model_copy(update={"sessionID":session})
    row, fresh = store.submit(request)
    assert fresh and row["id"] > 0
    assert store.submit(request)[1] is False
    with pytest.raises(ValueError, match="idempotency_conflict"):
        store.submit(request.model_copy(update={"command":"other"}))
    with pytest.raises(ValueError, match="task_busy"):
        store.submit(request.model_copy(update={"clientRequestID":"next"}))
    store.update(row["id"], "进行中")
    store.close()
    store = TaskStore(tmp_path / "tasks.db")
    assert store.get(row["id"])["state"] == "任务失败"
    assert store.binding(session)["uncertain"] == 1
    with pytest.raises(ValueError, match="reconciliation"):
        store.activate("b", session)
    new_session = store.activate("b")
    next_row, _ = store.submit(request.model_copy(update={"sessionID":new_session}))
    assert next_row["id"] > row["id"]
    store.close()


def test_all_ols_scenes_roundtrip_and_joint_inventory():
    root = Path(__file__).resolve().parents[2] / 'webeditor_runtime/ObjectLibraryServer-1.0.4-rel/data'
    inventory = Path('var/webeditor/joint_inventory.json')
    if not root.exists() or not inventory.exists():
        pytest.skip("external OLS 1.0.4 package/joint cache not installed")
    joints = json.loads(inventory.read_text())
    for item in json.loads((root/'scenes/scene_index.json').read_text()):
        original = json.loads((root/'scenes'/str(item['id'])/(item['name']+'.json')).read_text())
        scene = validate_web_scene(original, joints)
        assert scene.model_dump(mode="json") == original
    bad = scene.model_copy(deep=True)
    from robot_agent_brain.scene.component_access import SceneIndex
    SceneIndex(bad).component(2, "RobotDriver").properties["available_connect_joints"] = ["not_a_joint"]
    with pytest.raises(ValueError, match="urdf_joint_unknown"):
        validate_web_scene(bad, joints)


def test_only_one_service_owns_task_database(tmp_path):
    store = TaskStore(tmp_path/'tasks.db')
    with pytest.raises(ValueError,match="already_running"):
        TaskStore(tmp_path/'tasks.db')
    store.close()


def test_live_schema_requires_explicit_query_payload():
    from robot_agent_brain.models.task_understanding import task_understanding_wire_schema
    from jsonschema import Draft202012Validator
    schema = task_understanding_wire_schema()
    assert set(schema['required']) == set(schema['properties'])
    payload = {"arm_usage":"unspecified","hold_constraints":[],"status":"accepted","turn_kind":"scene_query",
               "robot_setup_request":None,"entities":[],"operations":[],"relations":[]}
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_synthetic_contract_fixtures_match_wire_schema(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('contract_export',Path(__file__).resolve().parents[1]/'scripts/export_webeditor_contract.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.export(tmp_path)
    task = StartTask.model_validate_json((tmp_path/'start_task.json').read_text())
    assert digest(task.scene) == task.sceneDigest
    commit=json.loads((tmp_path/'commit_world.json').read_text())
    receipt=json.loads((tmp_path/'commit_receipt.json').read_text())
    assert receipt['sceneDigest']==digest(commit['scene'])
