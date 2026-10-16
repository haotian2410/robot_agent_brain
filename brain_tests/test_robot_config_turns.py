import pytest
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.contracts.robot_profile import RobotProfileRegistry
from robot_agent_brain.models.task_understanding import TaskParseOutput
from test_dual_session_pipeline import configured
from test_robot_setup_manager import single_profile


def session():
    result, registry = configured()
    values = registry.model_dump()
    profile = single_profile().model_dump()
    profile.update(v2_robot="fixture_single_control", initial_state={"arms": {"single": {"state_known": True}}})
    values["profiles"]["fixture_single"] = profile
    values["default_single"] = "fixture_single"
    result.robot_profiles = RobotProfileRegistry.model_validate(values)
    return result


def test_config_only_switch_and_inherited_single_task():
    current = session()
    before = current.scene
    turn = BrainTurn(status="accepted", turn_kind="robot_config", instruction="改回单臂", robot_setup_request={"mode": "single"})
    changed = current.process_turn("switch", turn)
    assert changed.commands is None and changed.robot_setup_changed.mode == "single"
    assert current.scene.scene_version == before.scene_version + 1
    task = TaskParseOutput.model_validate({"entities": [{"id": "a", "name": "apple", "category": "fruit"}],
                                         "operations": [{"type": "grasp", "target": "a"}]}).to_brain_turn("抓苹果")
    result = current.process_turn("task", task)
    assert result.commands.schema_version == "2.0" and result.commands.robot == "fixture_single_control"
    assert current.pipeline.exporter.robot == "ur5e"
    back = BrainTurn(status="accepted", turn_kind="robot_config", instruction="换双臂", robot_setup_request={"mode": "dual"})
    current.process_turn("back", back)
    assert current.robot_setup.mode == "dual" and current.robot_setup_revision == 3


def test_combined_switch_and_plan_commits_both_only_on_success():
    current = session()
    turn = TaskParseOutput.model_validate({"robot_setup_request": {"mode": "single"},
        "entities": [{"id": "a", "name": "apple", "category": "fruit"}],
        "operations": [{"type": "grasp", "target": "a"}]}).to_brain_turn("用单臂抓苹果")
    before = current.scene
    result = current.process_turn("combined", turn)
    assert result.commands is not None and result.robot_setup_changed.mode == "single"
    assert result.commands.scene_version == before.scene_version + 1
    assert current.exported_commands["combined"]["scene_version"] == current.scene.scene_version


def test_combined_switch_failure_preserves_configuration():
    current = session()
    before, setup = current.scene, current.robot_setup.model_copy(deep=True)
    turn = TaskParseOutput.model_validate({"robot_setup_request": {"mode": "single"},
        "entities": [{"id": "a", "name": "missing_object", "category": "fruit"}],
        "operations": [{"type": "grasp", "target": "a"}]}).to_brain_turn("用单臂抓不存在的物体")
    with pytest.raises(ValueError):
        current.process_turn("bad", turn)
    assert current.scene == before and current.robot_setup == setup
    assert not current.exported_commands
