from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError

from robot_agent_brain.errors import BrainError
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.models.skill_planning import SkillPlanningRequest, SkillPlanLLMOutput, enrich_skill_plan
from robot_agent_brain.planning.context_builder import build_planner_context
from robot_agent_brain.skills.registry import REGISTRY
from test_qwen_http import response
from test_skill_planning_context import placement_task


def raw_plan():
    return {"operations": [{"id": "op-1", "intent": "Place source near destination", "steps": [
        {"skill": "locate", "target_role": "source"},
        {"skill": "move", "target_role": "source", "region": "grasp_region"},
        {"skill": "grasp", "target_role": "source"},
        {"skill": "locate", "target_role": "destination"},
        {"skill": "move", "target_role": "destination", "reference_role": "source", "region": "placement_region"},
        {"skill": "release", "target_role": "source", "reference_role": "destination", "region": "placement_region"},
    ]}]}


@pytest.mark.parametrize("cap,expected", [(128, 128), (1024, 512), (4096, 512)])
def test_http_planning_payload_budget_schema_and_metrics(cap, expected):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=response(raw=json.dumps(raw_plan())))
    provider = QwenHTTPProvider("http://example/v1", "test-model", api_key="test-key",
                               transport=httpx.MockTransport(handler), planner_max_completion_tokens=cap)
    output = provider.plan(SkillPlanningRequest(context=build_planner_context(placement_task()),
                                               skill_catalog=REGISTRY.prompt_catalog()))
    request = requests[0]
    assert request["temperature"] == 0 and request["model"] == "test-model"
    assert request["max_completion_tokens"] == expected
    assert request["response_format"]["type"] == "json_schema"
    schema = request["response_format"]["json_schema"]
    assert schema["name"] == "skill_planning" and schema["strict"] is True
    payload = json.loads(request["messages"][1]["content"])
    assert set(payload) == {"instruction", "semantic_summary", "operations", "entities", "goals", "initial_state", "skills"}
    assert "scene_object_id" not in json.dumps(payload)
    assert len(output.operations) == 1
    assert len(provider.calls) == 1 and provider.calls[0]["stage"] == "skill_planning"
    assert provider.calls[0]["total_tokens"] == 15


@pytest.mark.parametrize("field", ["scene_object_id", "asset_id", "xyz", "quaternion", "joint", "ik", "path",
                                  "trajectory", "distance_m", "step_id", "command_id", "depends_on", "target"])
def test_llm_steps_reject_physical_fields_and_python_ids(field):
    raw = raw_plan()
    raw["operations"][0]["steps"][0][field] = "forbidden"
    with pytest.raises(ValidationError):
        SkillPlanLLMOutput.model_validate(raw)


@pytest.mark.parametrize("mutation", ["duplicate", "unknown_skill", "invalid_role", "empty_intent", "empty_steps"])
def test_llm_output_contract(mutation):
    raw = raw_plan()
    op = raw["operations"][0]
    if mutation == "duplicate":
        raw["operations"].append(deepcopy(op))
    elif mutation == "unknown_skill":
        op["steps"][0]["skill"] = "go_home"
    elif mutation == "invalid_role":
        op["steps"][0]["target_role"] = "a_01"
    elif mutation == "empty_intent":
        op["intent"] = ""
    else:
        op["steps"] = []
    with pytest.raises(ValidationError):
        SkillPlanLLMOutput.model_validate(raw)


@pytest.mark.parametrize("mutation,code", [("missing", "planner_operation_order_mismatch"),
    ("extra", "planner_operation_order_mismatch"), ("reordered", "planner_operation_order_mismatch"),
    ("target_role", "planner_role_invalid"), ("reference_role", "planner_role_invalid"),
    ("null_target", "planner_role_invalid"), ("region", "planner_region_invalid")])
def test_enrich_exact_operations_and_roles(mutation, code):
    task = placement_task()
    raw = raw_plan()
    if mutation == "missing":
        raw["operations"] = []
    elif mutation in {"extra", "reordered"}:
        extra = deepcopy(raw["operations"][0])
        extra["id"] = "op-2"
        raw["operations"].append(extra)
        if mutation == "reordered":
            task.operations.append(task.operations[0].model_copy(update={"operation_id": "op-2"}))
            raw["operations"].reverse()
    elif mutation == "null_target":
        raw["operations"][0]["steps"][0]["target_role"] = None
    else:
        raw["operations"][0]["steps"][0][mutation] = "random_region" if mutation == "region" else "target"
    with pytest.raises(BrainError) as error:
        enrich_skill_plan(SkillPlanLLMOutput.model_validate(raw), task, REGISTRY)
    assert error.value.issue.code == code


def test_http_unknown_skill_has_stage_specific_error():
    raw = raw_plan()
    raw["operations"][0]["steps"][0]["skill"] = "go_home"
    provider = QwenHTTPProvider("http://example/v1", "test", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=response(raw=json.dumps(raw)))))
    with pytest.raises(QwenProviderError) as error:
        provider.plan(SkillPlanningRequest(context=build_planner_context(placement_task()), skill_catalog=REGISTRY.prompt_catalog()))
    assert error.value.code == "planner_unknown_skill"
    assert provider.last_raw_values["skill_planning"] == raw
    assert len(provider.calls) == 1 and provider.calls[0]["status"] == "failed"
