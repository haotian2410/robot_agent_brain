import copy
import pytest

from robot_agent_brain.models.dual_skill_planning import DualSkillPlanOutput
from test_dual_session_pipeline import configured, task


class Provider:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def plan_dual(self, request):
        self.calls.append(request)
        return DualSkillPlanOutput.model_validate(self.output)


def output():
    return {"stages": [{"left": None, "right": {"operation_id": "op-1", "skill": skill,
        "target_role": "target", "region": region}} for skill, region in
        (("locate", None), ("move", "grasp_region"), ("grasp", None))]}


def test_qwen_semantic_plan_one_call_and_python_ids():
    session, _ = configured(mode="qwen")
    provider = Provider(output())
    session.pipeline.skill_planner.provider = provider
    result = session.process_turn("qwen", task())
    assert result.planner_used == "qwen" and len(provider.calls) == 1
    assert result.commands.steps[0].arms.right.parameters.target == 7
    context = provider.calls[0].context
    assert context["operations"][0]["arm"] == "right"
    assert "scene_object_id" not in str(context) and "robot_object_id" not in str(context)
    assert result.commands.steps[2].preconditions
    assert session.arm_states.arms["right"].holding_object is None


@pytest.mark.parametrize("bad", ["wrong_arm", "missing_move", "wrong_role", "pour"])
def test_qwen_invalid_plan_never_falls_back(bad):
    session, _ = configured(mode="qwen")
    data = output()
    if bad == "wrong_arm":
        data["stages"][0]["left"] = data["stages"][0]["right"]
        data["stages"][0]["right"] = None
    elif bad == "missing_move":
        data["stages"].pop(1)
    elif bad == "wrong_role":
        data["stages"][0]["right"]["target_role"] = "destination"
    else:
        data["stages"][0]["right"]["skill"] = "pour"
    provider = Provider(data)
    session.pipeline.skill_planner.provider = provider
    with pytest.raises(ValueError):
        session.process_turn("bad", task())
    assert len(provider.calls) == 1 and not session.exported_commands


@pytest.mark.parametrize("serialize", [False, True])
def test_explicit_parallel_is_preserved_not_silently_serialized(serialize):
    from test_dual_recipe import task_scene
    from test_coordinated_validator import runtime
    from test_robot_profiles_state import fixture
    from robot_agent_brain.planning.dual_qwen_planner import DualQwenPlanner
    from robot_agent_brain.planning.skill_planner_router import PlanningTrace
    from robot_agent_brain.skills.registry import REGISTRY
    grounded, scene = task_scene()
    registry, _, _ = fixture()
    profile = registry.profiles["fixture_only"]
    stages = []
    for skill, region in (("locate", None), ("move", "grasp_region"), ("grasp", None)):
        stages.append({side: {"operation_id": op, "skill": skill, "target_role": "target", "region": region}
                       for side, op in (("left", "op-1"), ("right", "op-2"))})
    if serialize:
        stages = [{"left": s["left"], "right": None} for s in stages] + [{"left": None, "right": s["right"]} for s in stages]
    provider = Provider({"stages": stages})
    def run():
        return DualQwenPlanner().plan("q", grounded, scene, profile, 1, runtime(), provider, REGISTRY, PlanningTrace("qwen"))
    if serialize:
        with pytest.raises(ValueError, match="required_parallel_missing"):
            run()
    else:
        assert len(run().steps) == 3
