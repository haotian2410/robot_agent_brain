import pytest

from robot_agent_brain.contracts.robot_profile import RobotProfile
from robot_agent_brain.scene.robot_setup_manager import RobotSetupManager
from robot_agent_brain.scene.component_access import SceneIndex
from test_robot_profiles_state import fixture


def single_profile():
    registry, _, _ = fixture()
    values = registry.profiles["fixture_only"].model_dump()
    values["setup"] = {"mode": "single", "profile_id": "fixture_single",
                       "arms": {"single": values["setup"]["arms"]["left"]}}
    values["template"]["objects"] = [obj for obj in values["template"]["objects"] if obj["object_id_in_scene"] != 3]
    values.update(robot_object_ids={2}, platform_object_ids={2}, commands_version="2.0")
    return RobotProfile.model_validate(values)


def test_prepare_replaces_only_declared_robot_subgraph():
    _, scene, _ = fixture()
    before = scene.model_dump()
    target = single_profile()
    result = RobotSetupManager().prepare(scene, current_robot_ids={2, 3}, target_profile=target,
                                        platform_bindings={}, next_object_id=20)
    assert scene.model_dump() == before
    assert result.scene.scene_id == scene.scene_id and result.scene.scene_version == scene.scene_version + 1
    assert {o.object_id_in_scene for o in result.scene.objects} == {7, 20}
    assert SceneIndex(result.scene).object(7) == SceneIndex(scene).object(7)
    assert result.setup.mode == "single" and result.setup.arms["single"].robot_object_id == 20
    assert target.setup.arms["single"].robot_object_id == 2


def test_task_parented_to_old_robot_is_not_silently_moved():
    _, scene, _ = fixture()
    SceneIndex(scene).component(7, "Transform").properties["parent"] = 2
    before = scene.model_dump()
    with pytest.raises(ValueError, match="task_depends_on_old_robot"):
        RobotSetupManager().prepare(scene, current_robot_ids={2, 3}, target_profile=single_profile(),
                                    platform_bindings={}, next_object_id=20)
    assert scene.model_dump() == before


def test_platform_bindings_are_required_and_explicit():
    registry, scene, _ = fixture()
    values = single_profile().model_dump()
    values["platform_object_ids"] = {2, 7}  # fixture anchor only, not inferred
    target = RobotProfile.model_validate(values)
    with pytest.raises(ValueError, match="platform_binding_invalid"):
        RobotSetupManager().prepare(scene, current_robot_ids={2, 3}, target_profile=target,
                                    platform_bindings={}, next_object_id=20)
    result = RobotSetupManager().prepare(scene, current_robot_ids={2, 3}, target_profile=target,
                                        platform_bindings={7: 7}, next_object_id=20)
    assert result.platform_object_ids == {7, 20}


def test_session_switch_planning_failure_is_atomic():
    from test_dual_session_pipeline import configured
    session, _ = configured()
    before, revision, allocator = session.scene, session.robot_setup_revision, session.next_scene_object_id
    def fail(prepared, state, revision):
        raise ValueError("fixture_planning_failed")
    with pytest.raises(ValueError, match="planning_failed"):
        session.switch_robot_setup(single_profile(), platform_bindings={}, plan_candidate=fail)
    assert session.scene == before and session.robot_setup_revision == revision
    assert session.next_scene_object_id == allocator and session.sync_state == "synchronized"


def test_session_switch_commits_once_and_holding_blocks():
    from test_dual_session_pipeline import configured
    session, _ = configured()
    before = session.scene
    session.arm_states.arms["left"].holding_object = 7
    with pytest.raises(ValueError, match="holding_object"):
        session.switch_robot_setup(single_profile(), platform_bindings={})
    session.arm_states.arms["left"].holding_object = None
    prepared, result = session.switch_robot_setup(single_profile(), platform_bindings={})
    assert result is None and session.robot_setup.mode == "single"
    assert session.robot_setup_revision == 2 and session.scene.scene_version == before.scene_version + 1
    assert SceneIndex(session.scene).object(7) == SceneIndex(before).object(7)
    assert session.profile_object_map == prepared.template_id_map
    assert not session.arm_states.arms["single"].state_known
