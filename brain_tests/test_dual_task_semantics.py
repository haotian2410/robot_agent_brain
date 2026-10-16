import pytest

from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.contracts.task_intent import TaskIntent
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.models.task_understanding import TaskParseOutput
from robot_agent_brain.planning.task_expander import TaskExpander
from robot_agent_brain.semantics.task_domain_policy import TaskDomainPolicy


def parsed():
    return {"turn_kind": "robot_task", "robot_setup_request": {"mode": "dual"},
            "entities": [{"id": "apple", "name": "apple", "category": "fruit"},
                         {"id": "banana", "name": "banana", "category": "fruit"}],
            "operations": [{"type": "grasp", "target": "apple", "arm": "left", "parallel_group": "g1", "parallel_required": True},
                           {"type": "grasp", "target": "banana", "arm": "right", "parallel_group": "g1", "parallel_required": True}]}


def test_config_and_task_only_allowed_combination_and_no_default_mode():
    turn = TaskParseOutput.model_validate(parsed()).to_brain_turn("用双臂分别抓苹果和香蕉")
    assert turn.robot_setup_request.mode == "dual"
    assert [o.arm for o in turn.task_intent.operations] == ["left", "right"]
    with pytest.raises(ValueError, match="profile_not_registered"):
        turn.require_legacy_execution()
    data = parsed()
    data.pop("robot_setup_request")
    assert TaskParseOutput.model_validate(data).to_brain_turn("抓取").robot_setup_request is None
    config = TaskParseOutput(turn_kind="robot_config", robot_setup_request={"mode": "single"})
    assert config.to_brain_turn("换回单臂").task_intent is None
    for kind in ("scene_edit", "scene_query", "session_control"):
        with pytest.raises(ValueError):
            BrainTurn(status="accepted", turn_kind=kind, instruction="bad", robot_setup_request={"mode": "dual"})
    with pytest.raises(ValueError, match="rejected turn"):
        BrainTurn(status="clarification_required", turn_kind="robot_config", instruction="bad", robot_setup_request={"mode": "dual"})


def test_expansion_keeps_parallel_peers_and_barrier_after_both():
    task = TaskParseOutput.model_validate(parsed()).to_task_intent("抓取")
    task.operations.append(task.operations[0].model_copy(update={"operation_id": "op-3", "parallel_group": None, "parallel_required": False}))
    grounded = GroundedTask(instruction="抓取", scene_id=1, scene_version=1,
        entities=[{"entity_id": name, "semantic_name": name, "category": "fruit", "scene_object_id": i}
                  for i, name in enumerate(("apple", "banana"), 7)], operations=task.operations)
    expanded = TaskExpander().expand(grounded)
    assert expanded.operations[0].depends_on == []
    assert expanded.operations[1].depends_on == []
    assert expanded.operations[2].depends_on == ["op-1", "op-2"]


def test_parallel_dependency_conflict_rejected():
    data = parsed()
    data["operations"][1]["depends_on"] = ["op-1"]
    with pytest.raises(ValueError, match="parallel dependency conflict"):
        TaskParseOutput.model_validate(data).to_task_intent("bad")


def test_explicit_arm_move_is_not_reclassified_as_scene_edit():
    data = parsed()
    data["operations"] = [{"type": "move", "target": "apple", "arm": "left", "motion_direction": "right", "distance_m": .1}]
    turn = TaskParseOutput.model_validate(data).to_brain_turn("左臂将苹果右移十厘米")
    assert TaskDomainPolicy().classify(turn, turn.instruction).turn_kind == "robot_task"


def test_plain_single_arm_operation_remains_compatible():
    data = parsed()
    data.pop("robot_setup_request")
    data["operations"] = [{"type": "grasp", "target": "apple"}]
    turn = TaskParseOutput.model_validate(data).to_brain_turn("抓苹果")
    turn.require_legacy_execution()
    assert TaskIntent.model_validate(turn.task_intent.model_dump()) == turn.task_intent
