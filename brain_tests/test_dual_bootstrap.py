import json
from pathlib import Path

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.release_policy import ReleasePolicy
from robot_agent_brain.contracts.robot_profile import RobotProfileRegistry
from robot_agent_brain.models.task_understanding import TaskParseOutput
from test_robot_profiles_state import fixture
from test_component_runtime import object_
from test_application_artifacts import Provider


def registry():
    value, _, _ = fixture()
    values = value.model_dump()
    profile = values["profiles"]["fixture_only"]
    for obj in profile["template"]["objects"]:
        if obj["object_id_in_scene"] in (2, 3):
            for component in obj["components"]:
                if component["component_type"] == "MetadataRef":
                    component["properties"]["path"] = "$DEMO_LIBRARY/6"
    table = object_(0, "table", "surface", position=(0, 0, -.025), metadata_ref="$DEMO_LIBRARY/1").model_dump()
    for c in table["components"]:
        if c["component_type"] == "MetadataRef":
            c["properties"]["type"] = "model"
    profile["template"]["objects"].append(table)
    profile.update(platform_object_ids={0, 2, 3}, platform_roles={"table": 0}, default_task_arm="left",
        initial_state={"arms": {"left": {"state_known": True}, "right": {"state_known": True}}})
    return RobotProfileRegistry.model_validate(values)


def turn(kind="grasp"):
    return TaskParseOutput.model_validate({"robot_setup_request": {"mode": "dual"},
        "entities": [{"id": "a", "name": "apple", "category": "fruit"}],
        "operations": [{"type": kind, "target": "a", "arm": "right"}]}).to_brain_turn("用双臂的右臂抓苹果")


def test_public_application_rejects_dual_control_before_bootstrap(tmp_path):
    provider = Provider(turn())
    app = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path), robot_profiles=registry(),
        release_policy=ReleasePolicy(version="experiment", runtime_robot_setup_change=True,
                                     dynamic_platform_rebind=True)), provider=provider)
    report = app.handle("用双臂的右臂抓苹果")
    # A configured dual profile is not proof the integrated Control supports
    # dual execution. The public application is currently single-arm only.
    assert report.run_status != "success"
    assert report.error.code == "control_dual_arm_not_ready"
    assert not report.executed
    assert "commands" not in report.artifacts
    assert app.get_session(report.session_id).scene is None
    assert provider.count == 1
    assert not (tmp_path / report.session_id / "original_scene.json").exists()


def test_profile_bootstrap_failed_plan_never_loads_scene(tmp_path):
    # Release without a held object is a deterministic planning failure.
    app = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path), robot_profiles=registry(),
        release_policy=ReleasePolicy(version="experiment", runtime_robot_setup_change=True,
                                     dynamic_platform_rebind=True)), provider=Provider(turn("release")))
    report = app.handle("用双臂的右臂释放苹果")
    assert report.run_status != "success"
    assert app.get_session(report.session_id).scene is None
    assert not (tmp_path / report.session_id / "original_scene.json").exists()


def test_configuration_only_first_turn_does_not_freeze_platform(tmp_path):
    config_turn = TaskParseOutput(turn_kind="robot_config", robot_setup_request={"mode": "dual"}).to_brain_turn("换成双臂")
    app = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path), robot_profiles=registry(),
        release_policy=ReleasePolicy(version="experiment", runtime_robot_setup_change=True,
                                     dynamic_platform_rebind=True)), provider=Provider(config_turn))
    report = app.handle("换成双臂")
    assert report.run_status == "success", report
    assert report.delivery_status == "robot_configured" and "commands" not in report.artifacts
    assert not (tmp_path / report.session_id / "original_scene.json").exists()
