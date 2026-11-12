"""Round three against the control prose specification: no grammar, one repair turn."""
import json

import httpx
import pytest

from robot_agent_brain.contracts.commands_atomic import AtomicCommandsFile
from robot_agent_brain.models.prompts import ATOMIC_SKILL_PLANNING_PROMPT
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.planning.atomic_plan_validator import AtomicPlanValidator
from robot_agent_brain.planning.context_builder import build_planner_context
from test_qwen_http import response
from test_skill_planning_context import placement_task


def commands(source=101, destination=102):
    return {"commands": [
        {"command_id": "1", "skill_name": "approach", "parameters": {"target": source}},
        {"command_id": "2", "skill_name": "pick", "parameters": {"target": source}},
        {"command_id": "3", "skill_name": "lift_up", "parameters": {"distance": 0.02}},
        {"command_id": "4", "skill_name": "retreat", "parameters": {"target": source}},
        {"command_id": "5", "skill_name": "move_to", "parameters": {"target": "home", "planning_method": "joint"}},
        {"command_id": "6", "skill_name": "approach", "parameters": {"target": destination}},
        {"command_id": "7", "skill_name": "put", "parameters": {"target": destination}},
        {"command_id": "8", "skill_name": "retreat", "parameters": {"target": destination}}]}


def provider_for(bodies, **kwargs):
    pending = iter(bodies)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response(raw=next(pending)))
    return QwenHTTPProvider("http://example/v1", "test-model", api_key="test-key",
                            transport=httpx.MockTransport(handler), **kwargs), requests


def context():
    return build_planner_context(placement_task())


def assembly_guard(task=None):
    """The same guard AtomicPlanner installs, so a violation is the model's problem."""
    validator, bound = AtomicPlanValidator(), task or placement_task()

    def guard(draft):
        numbered = [command.model_copy(update={"command_id": str(index)})
                    for index, command in enumerate(draft.commands, 1)]
        validator.validate(AtomicCommandsFile(request_id="r-1", scene_id=1, scene_version=0,
                                              commands=numbered), bound)
    return guard


def test_payload_uses_the_control_prompt_without_a_skill_catalog():
    provider, requests = provider_for([json.dumps(commands())])
    draft = provider.plan_atomic(context())
    request = requests[0]
    assert request["messages"][0]["content"] == ATOMIC_SKILL_PLANNING_PROMPT
    assert request["temperature"] == 0 and request["model"] == "test-model"
    assert "skills" not in request["messages"][1]["content"]
    payload = json.loads(request["messages"][1]["content"])
    assert set(payload) == {"instruction", "semantic_summary", "operations", "entities", "goals", "initial_state"}
    assert [entity["scene_object_id"] for entity in payload["entities"]] == [101, 102]
    assert payload["operations"][0]["role_object_ids"] == {"source": 101, "destination": 102}
    assert len(draft.commands) == 8
    assert provider.calls[0]["stage"] == "skill_planning"


@pytest.mark.parametrize("cap,expected", [(128, 128), (1024, 768), (4096, 768)])
def test_output_budget_scales_with_commands_not_steps(cap, expected):
    provider, requests = provider_for([json.dumps(commands())], planner_max_completion_tokens=cap)
    provider.plan_atomic(context())
    assert requests[0]["max_completion_tokens"] == expected


@pytest.mark.parametrize("structured,answer_format,expected", [
    (True, "json_object", {"type": "json_object"}),
    (True, "json_schema", "strict"),
    (False, "json_object", None),
])
def test_grammar_is_only_an_opt_in(structured, answer_format, expected):
    provider, requests = provider_for([json.dumps(commands())], structured_output=structured,
                                      skill_planning_response_format=answer_format)
    provider.plan_atomic(context())
    format_payload = requests[0].get("response_format")
    if expected is None:
        assert "response_format" not in requests[0]
        assert provider.calls[0]["response_format"] == "text"
    elif expected == "strict":
        assert format_payload["json_schema"]["strict"] is True
        assert format_payload["json_schema"]["name"] == "skill_planning"
    else:
        assert format_payload == expected
        assert "json_schema" not in json.dumps(requests[0])


def test_json_fence_is_accepted_without_a_repair_turn():
    provider, _ = provider_for(["```json\n" + json.dumps(commands()) + "\n```"])
    assert len(provider.plan_atomic(context()).commands) == 8
    assert len(provider.calls) == 1


def test_bare_array_answer_gets_exactly_one_repair_turn():
    provider, requests = provider_for([json.dumps(commands()["commands"]), json.dumps(commands())])
    draft = provider.plan_atomic(context())
    assert len(draft.commands) == 8 and len(provider.calls) == 2
    assert "上一轮输出不被接受" in requests[1]["messages"][0]["content"]
    assert requests[1]["messages"][0]["content"].startswith(ATOMIC_SKILL_PLANNING_PROMPT)


def test_illegal_assemblies_are_rejected_not_repaired():
    missing_retreat = commands()
    missing_retreat["commands"].pop()
    unknown_target = commands()
    unknown_target["commands"][6]["parameters"]["target"] = 999
    unspelled_relation = commands()
    unspelled_relation["commands"][6]["parameters"]["relation"] = "highest"
    unknown_parameter = commands()
    unknown_parameter["commands"][0]["parameters"]["gripper"] = "close"
    invented_skill = commands()
    invented_skill["commands"][0]["skill_name"] = "go_home"
    cases = [(missing_retreat, "atomic_plan_missing_retreat"), (unknown_target, "atomic_plan_unknown_target"),
             (unspelled_relation, "skill_plan_output_invalid"),
             (unknown_parameter, "skill_plan_output_invalid"),
             (invented_skill, "planner_unknown_skill")]
    for broken, code in cases:
        provider, requests = provider_for([json.dumps(broken), json.dumps(broken)])
        with pytest.raises(QwenProviderError) as error:
            provider.plan_atomic(context(), validate=assembly_guard())
        assert error.value.code == code
        assert len(provider.calls) == 2, code
        assert "上一轮输出不被接受" in requests[1]["messages"][0]["content"]
        assert provider.calls[-1]["status"] == "failed"


def test_valid_answer_after_a_violation_is_accepted():
    broken = commands()
    broken["commands"].pop()
    provider, requests = provider_for([json.dumps(broken), json.dumps(commands())])
    draft = provider.plan_atomic(context(), validate=assembly_guard())
    assert len(draft.commands) == 8
    assert "atomic_plan_missing_retreat" in requests[1]["messages"][0]["content"]


def test_truncated_answer_is_retried_with_a_bigger_budget():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        body = response(raw=json.dumps(commands()))
        if len(requests) == 1:
            body["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=body)
    provider = QwenHTTPProvider("http://example/v1", "test", transport=httpx.MockTransport(handler),
                                planner_max_completion_tokens=1024)
    assert len(provider.plan_atomic(context()).commands) == 8
    assert [request["max_completion_tokens"] for request in requests] == [768, 1024]


def test_truncation_is_not_retried_past_the_configured_cap():
    body = {"choices": [{"message": {"content": json.dumps(commands())}, "finish_reason": "length"}],
            "usage": {"total_tokens": 15}}

    provider = QwenHTTPProvider("http://example/v1", "test", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=body)), planner_max_completion_tokens=768)
    with pytest.raises(QwenProviderError, match="model_output_truncated"):
        provider.plan_atomic(context())
    assert len(provider.calls) == 1
