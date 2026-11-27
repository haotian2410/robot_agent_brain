import copy
import pytest
from robot_agent_brain.contracts.dual_skill_draft import DualSkillDraft
from test_dual_v4_pipeline import setup
from test_dual_session_pipeline import task


class Provider:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def plan_dual_operations(self, request):
        self.calls.append(request)
        return DualSkillDraft.model_validate(self.output)


def output():
    return {"operations": [{"operation_id": "op-1",
        "steps": [{"skill_name": "pick", "parameters": {"source": 7}}]}]}


def test_qwen_semantic_plan_one_call_and_python_ids():
    session = setup("qwen")
    provider = Provider(output())
    session.pipeline.skill_planner.provider = provider
    result = session.process_turn("qwen", task())
    assert result.planner_used == "qwen" and len(provider.calls) == 1
    command = result.commands.commands[0]
    assert command.parameters == {"source": 7}
    assert command.arm == "right"
    assert command.command_id == "R-op-1-1"
    assert session.arm_states.arms["right"].holding_object is None


@pytest.mark.parametrize("bad", ["arm", "missing_operation", "wrong_source", "pour", "stages", "sync"])
def test_qwen_invalid_plan_never_falls_back(bad):
    session = setup("qwen")
    data = copy.deepcopy(output())
    if bad == "arm":
        data["operations"][0]["steps"][0]["arm"] = "left"
    elif bad == "missing_operation":
        data["operations"][0]["operation_id"] = "other"
    elif bad == "wrong_source":
        data["operations"][0]["steps"][0]["parameters"]["source"] = 8
    elif bad == "pour":
        data["operations"][0]["steps"][0]["skill_name"] = "pour"
    elif bad == "stages":
        data = {"stages": []}
    else:
        data["sync_groups"] = []
    provider = Provider(data)
    session.pipeline.skill_planner.provider = provider
    with pytest.raises(ValueError):
        session.process_turn("bad", task())
    assert len(provider.calls) == 1
    assert not session.exported_commands
