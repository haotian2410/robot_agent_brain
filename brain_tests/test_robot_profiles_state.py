import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.robot_profile import RobotProfileRegistry
from robot_agent_brain.contracts.robot_setup import RobotSetupRequest, RobotRuntimeState
from robot_agent_brain.contracts.commands_v3 import CommandsFileV3
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.store import SessionState, SessionStore
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from test_dual_commands_contract import example
from test_component_runtime import object_


def fixture():
    setup = CommandsFileV3.model_validate(example()).robot_setup
    objects = []
    for i in (2, 3):
        obj = object_(i, "robot")
        obj.components = [c for c in obj.components if c.component_type != "MetadataRef"]
        from robot_agent_brain.contracts.scene import SceneComponent
        obj.components.extend([SceneComponent(component_type="MetadataRef", properties={"path": "$LIBRARY_SERVER/14", "type": "robot"}),
                               SceneComponent(component_type="RobotDriver", properties={"joint_sequence": ["joint1"], "available_connect_joints": []})])
        objects.append(obj)
    objects.append(object_(7, "apple"))
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="fixture", objects=objects)
    registry = RobotProfileRegistry.model_validate({"default_dual": "fixture_only", "profiles": {"fixture_only": {
        "setup": setup, "template": scene, "robot_object_ids": [2, 3], "platform_object_ids": [2, 3],
        "supported_skills": ["locate", "move", "grasp", "release"], "commands_version": "3.0"}}})
    return registry, scene, setup


def test_registry_explicit_mapping_and_defensive_copy():
    registry, scene, setup = fixture()
    profile = registry.resolve(RobotSetupRequest(mode="dual"))
    profile.setup.arms["left"].planning_group = "changed"
    assert registry.profiles["fixture_only"].setup == setup
    with pytest.raises(ValueError, match="not_registered"):
        registry.resolve(RobotSetupRequest(mode="single"))
    bad = registry.model_dump()
    bad["profiles"]["fixture_only"]["commands_version"] = "2.0"
    with pytest.raises(ValueError, match="dual_requires_v3"):
        RobotProfileRegistry.model_validate(bad)
    assert BrainConfig(robot_profiles=registry).robot_profiles.default_dual == "fixture_only"


def test_v2_checkpoint_preserves_per_arm_unknown_and_isolation(tmp_path):
    _, scene, setup = fixture()
    session = BrainSession(scene, None, LocalScenePlatform())
    session.robot_setup = setup
    session.robot_setup_revision = 2
    session.arm_states = RobotRuntimeState(arms={"left": {"state_known": True, "holding_object": 7},
                                                "right": {"state_known": False}})
    store = SessionStore(tmp_path)
    with store.lock("s"):
        store.save("s", session, revision=1)
        state = store.load("s")
    assert state.version == "2.0"
    restored = store.restore(state, BrainSession(None, None, LocalScenePlatform()))
    assert restored.arm_states == session.arm_states
    restored.arm_states.arms["left"].holding_object = None
    assert session.arm_states.arms["left"].holding_object == 7
    assert not restored.arm_states.arms["right"].state_known


def test_legacy_migration_does_not_invent_profile_or_arm_evidence():
    _, scene, _ = fixture()
    old = {"version": "1.0", "session_id": "legacy", "revision": 1, "scene": scene,
           "seen_scene_object_ids": {2, 3, 7}, "next_scene_object_id": 8, "holding_object": 7}
    state = SessionState.model_validate(old)
    assert state.version == "2.0" and state.holding_object == 7
    assert state.robot_setup is None and state.arm_states is None
    assert state.robot_setup_revision == 0
