import pytest

from robot_agent_brain.models.task_understanding import TaskParseOutput
from test_dual_session_pipeline import configured
from test_component_runtime import object_


def request(count=2, usage="both_required", arm=None):
    return TaskParseOutput.model_validate({
        "arm_usage": usage,
        "entities": [{"id": "apple", "name": "apple", "category": "fruit",
                      "count": count, "quantity_mode": "all"}],
        "operations": [{"type": "grasp", "target": "apple", "arm": arm}],
    }).to_brain_turn("用左右两臂分别抓苹果" if usage == "both_required" else "在双臂平台抓苹果")


def test_both_required_assigns_distinct_expanded_instances():
    session, _ = configured()
    scene = session.scene
    scene.objects.append(object_(9, "apple", "fruit"))
    session.initialize_scene(scene)
    session.bind_imported_profile(session.robot_profiles.profiles["fixture_only"])
    turn = request()
    assert turn.task_intent.arm_usage == "both_required"
    result = session.process_turn("two", turn)
    assert [o.arm for o in result.grounded_task.operations] == ["left", "right"]
    grasps = [(arm, action.parameters.target) for step in result.commands.steps
              for arm, action in (("left", step.arms.left), ("right", step.arms.right))
              if action is not None and action.skill_name == "grasp"]
    assert len(grasps) == 2
    assert len({object_id for _, object_id in grasps}) == 2


def test_both_required_single_exclusive_object_rejected():
    session, _ = configured()
    with pytest.raises(ValueError, match="capability_unsupported"):
        session.process_turn("one", request(1))
    assert not session.exported_commands


def test_platform_only_keeps_default_and_explicit_arm():
    for arm, expected in ((None, "left"), ("right", "right")):
        session, _ = configured()
        result = session.process_turn("one", request(1, "unspecified", arm))
        assert result.grounded_task.operations[0].arm == expected


def test_cannot_override_explicit_arm_to_satisfy_both_required():
    session, _ = configured()
    scene = session.scene
    scene.objects.append(object_(9, "apple", "fruit"))
    session.initialize_scene(scene)
    session.bind_imported_profile(session.robot_profiles.profiles["fixture_only"])
    with pytest.raises(ValueError, match="capability_unsupported"):
        session.process_turn("two", request(2, arm="left"))


def test_both_required_cannot_escape_into_single_arm_v2():
    with pytest.raises(ValueError, match="dual_arm_execution_not_configured"):
        request().require_legacy_execution()


def test_logical_assignment_preserves_three_member_order_and_dependencies():
    from robot_agent_brain.contracts.grounded_task import GroundedTask
    from robot_agent_brain.planning.task_expander import TaskExpander
    from robot_agent_brain.planning.arm_assignment_resolver import resolve_arms
    _, registry = configured()
    task = GroundedTask(instruction="three", scene_id=1, scene_version=1,
        entities=[{"entity_id": "apple", "semantic_name": "apple", "category": "fruit",
                   "scene_object_id": 7, "scene_object_ids": [7, 9, 10]}],
        operations=[{"operation_id": "op-1", "task_type": "move", "target": "apple",
                     "motion_direction": "right", "distance_m": .1}])
    expanded = TaskExpander().expand(task)
    allocated = resolve_arms(expanded, registry.profiles["fixture_only"], arm_usage="both_required")
    assert [o.arm for o in allocated.operations] == ["left", "right", "left"]
    assert [o.depends_on for o in allocated.operations] == [o.depends_on for o in expanded.operations]
    assert [e.scene_object_id for e in allocated.entities] == [7, 9, 10]


def test_explicit_simultaneous_collection_has_no_artificial_internal_dependency():
    session, registry = configured()
    scene = session.scene
    scene.objects.append(object_(9, "apple", "fruit"))
    session.initialize_scene(scene)
    session.bind_imported_profile(registry.profiles["fixture_only"])
    turn = request()
    turn.task_intent.operations[0].parallel_group = "both"
    turn.task_intent.operations[0].parallel_required = True
    result = session.process_turn("parallel", turn)
    assert all(not op.depends_on for op in result.grounded_task.operations)
    assert all(step.arms.left is not None and step.arms.right is not None for step in result.commands.steps)


def test_model_cannot_omit_explicit_both_hands_requirement():
    parsed = {"entities": [{"id": "apple", "name": "apple", "category": "fruit", "count": 2, "quantity_mode": "all"}],
              "operations": [{"type": "grasp", "target": "apple"}]}
    with pytest.raises(ValueError, match="arm_usage_required"):
        TaskParseOutput.model_validate(parsed).to_task_intent("用双臂分别抓两个苹果，两只手各抓一个苹果")
