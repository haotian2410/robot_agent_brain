import pytest
from robot_agent_brain.models.task_understanding import TaskParseWireOutput, TaskUnderstandingRequest
from robot_agent_brain.models.understanding_wire import encode
from robot_agent_brain.models.qwen_http import QwenProviderError
from test_layout_qwen_planning import provider_for
from test_scene_layout_route import payload


def response(wire):
    layout = TaskParseWireOutput.model_validate(payload()).model_dump(mode="json")
    robot = TaskParseWireOutput.model_validate({
        "turn_kind": "robot_task", "entities": [{"entity_id": "apple",
        "semantic_name": "apple", "category": "fruit"}],
        "operations": [{"operation": "grasp", "target": "apple"}],
    }).model_dump(mode="json")
    if wire == "compact_v1":
        layout, robot = encode(layout), encode(robot)
    return {"phases": [{"instruction": "排列两个苹果", "payload": layout},
                       {"instruction": "抓起苹果", "payload": robot}]}


@pytest.mark.parametrize("wire", ["full", "compact_v1"])
def test_one_request_parses_all_phases_without_second_understanding(wire):
    requests = []
    provider = provider_for(response(wire), requests)
    provider.understanding_wire_format = wire
    task = provider.understand_composite(TaskUnderstandingRequest(instruction="排列苹果然后抓起"))
    assert len(requests) == 1
    assert [p.turn_kind.value for p in task.phases] == ["scene_layout", "robot_task"]
    assert task.phases[0].arrangement_spec.items.requested_count == 2
    assert task.phases[1].task_intent.operations[0].target == "apple"
    assert provider.calls[0]["stage"] == "composite_understanding"
    assert provider.last_raw_values["composite_understanding_canonical"][1]["turn_kind"] == "robot_task"


@pytest.mark.parametrize("wire", ["full", "compact_v1"])
def test_invalid_phase_is_rejected_without_retry_or_partial_execution(wire):
    value = response(wire)
    value["phases"][1]["payload"]["unexpected"] = True
    requests = []
    provider = provider_for(value, requests)
    provider.understanding_wire_format = wire
    with pytest.raises(QwenProviderError):
        provider.understand_composite(TaskUnderstandingRequest(instruction="排列苹果然后抓起"))
    assert len(requests) == 1


def test_session_consumes_single_u_response_and_binds_created_instance():
    from test_composite_scene_robot import session_and_task
    session, _ = session_and_task()
    value = response("full")
    spec = value["phases"][0]["payload"]["arrangement_spec"]
    spec["items"]["requested_count"] = 1
    spec["pattern"]["cols"] = 1
    value["phases"][0]["instruction"] = "排列一个苹果"
    requests = []
    provider = provider_for(value, requests)
    provider.understanding_wire_format = "full"
    session.pipeline.understanding = provider
    results = session.run_composite_task("single-u", "排列一个苹果然后抓起它")
    assert len(requests) == 1
    assert results[1].grounded_task.entities[0].scene_object_id == results[0].layout_resolution.instance_ids[0]
    assert [p["status"] for p in session.composite_turn_records[-1]["phases"]] == ["committed", "planned"]
