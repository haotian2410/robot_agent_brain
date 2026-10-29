from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.semantics.task_domain_policy import TaskDomainPolicy


def edit(instruction, basis="current"):
    return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=instruction,
        scene_edit={"scene_basis": basis,
                    "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
                    "operations": [{"operation": "translate", "target": "apple", "direction": "right", "distance_m": .1}]})


def test_left_arm_survives_domain_correction():
    text = "左臂把苹果右移10厘米"
    result = TaskDomainPolicy().classify(edit(text), text)
    assert result.turn_kind == "robot_task"
    assert result.task_intent.operations[0].arm == "left"


def test_ambiguous_dual_domain_correction_clarifies():
    text = "用双臂分别把两个苹果右移10厘米"
    result = TaskDomainPolicy().classify(edit(text), text)
    assert result.status == "clarification_required"
    assert result.task_intent is None


def test_original_edit_is_never_sent_to_control():
    text = "在原始场景用左臂把苹果右移10厘米"
    result = TaskDomainPolicy().classify(edit(text, "original"), text)
    assert result.status == "clarification_required"
    assert result.task_intent is None


def test_unregistered_pour_cannot_be_disguised_as_grasp_by_model():
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    parsed = TaskParseOutput.model_validate({"robot_setup_request": {"mode": "dual"},
        "entities": [{"id": "cup", "name": "cup", "category": "container"}],
        "operations": [{"type": "grasp", "target": "cup", "arm": "left"}]})
    text = "用双臂倒水"
    result = TaskDomainPolicy().classify(parsed.to_brain_turn(text), text)
    assert result.status == "unsupported_task" and result.task_intent is None


def test_explicit_scene_placement_is_not_downgraded_by_interaction_word():
    text = "在桌面上放置一个苹果"
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction=text,
        scene_edit={"entities": [
            {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
            {"entity_id": "table", "semantic_name": "table", "category": "surface"},
        ], "operations": [{"operation": "add", "target": "apple",
                            "relation": "on", "reference": "table"}]})
    result = TaskDomainPolicy().classify(turn, text)
    assert result.status == "accepted"
    assert result.turn_kind == "scene_edit"
