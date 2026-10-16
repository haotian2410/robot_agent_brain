import pytest

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.robot_profile import RobotProfileRegistry
from robot_agent_brain.models.task_understanding import TaskParseOutput
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.store import SessionStore
from conftest import apple_assets
from test_robot_profiles_state import fixture
from test_component_runtime import object_


def configured(mode="recipe"):
    registry, scene, _ = fixture()
    scene.objects.append(object_(8, "banana", "fruit"))
    data = registry.model_dump()
    data["profiles"]["fixture_only"].update(default_task_arm="left", coordinated_execution=True,
        initial_state={"arms": {"left": {"state_known": True}, "right": {"state_known": True}}})
    registry = RobotProfileRegistry.model_validate(data)
    pipeline = BrainPipeline(None, apple_assets(), planner_mode=mode)
    session = BrainSession(scene, pipeline, LocalScenePlatform(), robot_profiles=registry)
    session.bind_imported_profile(registry.profiles["fixture_only"])
    return session, registry


def task(arm="right"):
    return TaskParseOutput.model_validate({"entities": [{"id": "apple", "name": "apple", "category": "fruit"}],
        "operations": [{"type": "grasp", "target": "apple", "arm": arm}]}).to_brain_turn("抓苹果")


def test_session_generates_v3_and_inherits_dual_on_next_turn(tmp_path):
    session, registry = configured()
    first = session.process_turn("first", task())
    assert first.commands.schema_version == "3.0"
    assert first.skill_plan is None
    assert all(stage.arms.left is None for stage in first.commands.steps)
    assert session.arm_states.arms["right"].holding_object is None  # plan != execution
    store = SessionStore(tmp_path)
    with store.lock("s"):
        store.save("s", session, revision=1)
        saved = store.load("s")
    resumed = store.restore(saved, BrainSession(None, session.pipeline, LocalScenePlatform(), robot_profiles=registry))
    second = resumed.process_turn("second", task(arm=None))
    assert second.commands.robot_setup.mode == "dual"
    assert all(stage.arms.right is None for stage in second.commands.steps)
    assert second.commands.robot_setup_revision == 1


def test_qwen_mode_never_silently_uses_recipe():
    session, _ = configured(mode="qwen")
    with pytest.raises(ValueError, match="dual_qwen_planner_not_configured"):
        session.process_turn("q", task())
    assert not session.exported_commands


def test_no_initial_state_declaration_does_not_invent_empty_grippers():
    session, registry = configured()
    session.initialize_scene(session.scene)
    profile = registry.profiles["fixture_only"].model_copy(update={"initial_state": None})
    session.bind_imported_profile(profile)
    with pytest.raises(ValueError, match="state_unknown"):
        session.process_turn("unknown", task())


def test_sessions_do_not_mutate_shared_robot_or_state():
    left, registry = configured()
    right = BrainSession(left.scene, left.pipeline, LocalScenePlatform(), robot_profiles=registry)
    right.bind_imported_profile(registry.profiles["fixture_only"])
    left.arm_states.arms["left"].holding_object = 7
    assert right.arm_states.arms["left"].holding_object is None
    assert left.pipeline.exporter.robot == "ur5e"
