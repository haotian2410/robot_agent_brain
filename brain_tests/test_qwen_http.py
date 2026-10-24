import json
import httpx
import pytest
from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest


PAUSE = {"status":"accepted", "turn_kind":"session_control", "session_control":{"action":"pause"}}


def response(raw=None, **overrides):
    return {"choices":[{"message":{"content":json.dumps(PAUSE) if raw is None else raw}, "finish_reason":"stop"}],
            "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}, **overrides}


def test_injected_client_success_and_single_record():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response(), headers={"x-request-id":"server-1"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = QwenHTTPProvider("http://example/v1", "qwen-test", client=client)
        turn = provider.understand_turn(TaskUnderstandingRequest(instruction="pause"))
        assert turn.turn_kind == "session_control"
        assert requests[0]["response_format"]["type"] == "json_schema"
        assert {"arm_usage", "hold_constraints"} <= set(requests[0]["response_format"]["json_schema"]["schema"]["required"])
        assert len(provider.calls) == 1
        call = provider.calls[0]
        assert call["status"] == "succeeded" and call["usage"]["total_tokens"] == 15
        assert call["response_request_id"] == "server-1" and call["elapsed_seconds"] >= 0
        assert "raw_text" not in call


@pytest.mark.parametrize("body", [
    response(raw="{bad"),
    response(choices=[]),
    response(choices=[{"message":{"content":[]},"finish_reason":"stop"}]),
    response(raw='{"status":"accepted","turn_kind":"robot_task"}'),
    response(raw="```json\n{}"),
    response(choices=[{"message":{"content":'{"unfinished":'},"finish_reason":"length"}]),
    [],
])
def test_every_parse_failure_has_exactly_one_failed_record(body):
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(QwenProviderError):
        provider.understand_turn(TaskUnderstandingRequest(instruction="pause"))
    assert len(provider.calls) == 1 and provider.calls[0]["status"] == "failed"
    assert provider.last_raw_text["task_understanding"]
    if isinstance(body, dict) and body.get("usage"):
        assert provider.calls[0]["total_tokens"] == 15
    if isinstance(body, dict) and body.get("choices") and body["choices"][0].get("finish_reason") == "length":
        assert "model_output_truncated" in provider.calls[0]["error"]


@pytest.mark.parametrize("mode", ["timeout", "http_error", "body_json"])
def test_transport_and_body_failures_redact_secret(mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("secret-token timeout", request=request)
        if mode == "http_error":
            return httpx.Response(503, text="secret-token unavailable")
        return httpx.Response(200, text="secret-token not-json")
    provider = QwenHTTPProvider("http://example/v1", "qwen-test", api_key="secret-token",
                                transport=httpx.MockTransport(handler))
    with pytest.raises(QwenProviderError) as error:
        provider.understand_turn(TaskUnderstandingRequest(instruction="pause"))
    assert "secret-token" not in str(error.value)
    assert "secret-token" not in json.dumps(provider.calls)
    assert "secret-token" not in json.dumps(provider.last_raw_text)
    assert len(provider.calls) == 1 and provider.calls[0]["status"] == "failed"


def test_application_records_only_current_round(tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response())))
    app = BrainApplication(BrainConfig(output_dir=str(tmp_path), model="qwen-test"), provider=provider)
    first, second = app.handle("pause"), app.handle("pause")
    assert len(provider.calls) == 2
    assert len(first.metrics["model_calls"]) == len(second.metrics["model_calls"]) == 1
    assert first.metrics["model_calls"][0]["request_id"] != second.metrics["model_calls"][0]["request_id"]


def _task_payload(**updates):
    value = {
        "arm_usage": "unspecified", "hold_constraints": [], "status": "accepted",
        "turn_kind": "robot_task", "clarification_question": None,
        "scene_edit": None, "scene_query": None, "session_control": None,
        "robot_setup_request": None,
        "entities": [{"id": "door", "name": "microwave_door", "category": "door"}],
        "operations": [{"type": "open", "target": "door", "reference": "handle"}],
        "relations": [],
    }
    value.update(updates)
    return value


@pytest.mark.parametrize("task_type", ["open", "close"])
def test_qwen_missing_open_close_reference_becomes_clarification(task_type):
    raw = _task_payload(operations=[{"type": task_type, "target": "door"}])
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response(raw=json.dumps(raw)))))
    turn = provider.understand_turn(TaskUnderstandingRequest(instruction=f"{task_type} microwave door"))
    assert turn.status.value == "clarification_required"
    assert turn.clarification_question and "参照物" in turn.clarification_question
    assert turn.task_intent is None and turn.robot_setup_request is None
    assert provider.calls[0]["status"] == "succeeded"


def test_qwen_invalid_clarification_payload_is_sanitized():
    raw = _task_payload(
        status="clarification_required", arm_usage="both_required",
        robot_setup_request={"mode": "dual", "profile_id": None},
        clarification_question="请明确双臂分工",
    )
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response(raw=json.dumps(raw)))))
    turn = provider.understand_turn(TaskUnderstandingRequest(instruction="双臂抓取"))
    assert turn.status.value == "clarification_required"
    assert turn.clarification_question == "请明确双臂分工"
    assert turn.task_intent is None and turn.robot_setup_request is None


def test_qwen_unsupported_payload_is_sanitized():
    raw = _task_payload(
        status="unsupported_task", arm_usage="both_required",
        operations=[{"type": "grasp", "target": "door"}],
        clarification_question="当前技能未注册",
    )
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response(raw=json.dumps(raw)))))
    turn = provider.understand_turn(TaskUnderstandingRequest(instruction="倒水"))
    assert turn.status.value == "unsupported_task"
    assert turn.turn_kind.value == "unsupported_task"
    assert turn.clarification_question == "当前技能未注册"
    assert turn.task_intent is None and turn.robot_setup_request is None


def test_qwen_valid_open_close_reference_remains_accepted():
    raw = _task_payload(operations=[{"type": "open", "target": "door", "reference": "handle"}],
                        entities=[{"id": "door", "name": "microwave_door", "category": "door"},
                                  {"id": "handle", "name": "handle", "category": "handle"}])
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response(raw=json.dumps(raw)))))
    turn = provider.understand_turn(TaskUnderstandingRequest(instruction="open microwave door by handle"))
    assert turn.status.value == "accepted"
    assert turn.task_intent.operations[0].reference == "handle"


def test_qwen_unrelated_accepted_invalid_output_stays_provider_error():
    raw = _task_payload(operations=[{"type": "grasp"}])
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response(raw=json.dumps(raw)))))
    with pytest.raises(QwenProviderError) as error:
        provider.understand_turn(TaskUnderstandingRequest(instruction="grasp"))
    assert error.value.code == "provider_error"


def test_direct_task_parse_keeps_missing_reference_strict():
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    raw = _task_payload(operations=[{"type": "open", "target": "door"}])
    with pytest.raises(ValueError, match="reference"):
        TaskParseOutput.model_validate(raw).to_brain_turn("打开微波炉门")


def test_application_reports_clarification_without_scene_or_commands(tmp_path):
    raw = _task_payload(
        status="clarification_required", arm_usage="both_required",
        clarification_question="请明确双臂分工",
    )
    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response(raw=json.dumps(raw)))))
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    report = BrainApplication(BrainConfig(output_dir=str(tmp_path), model="qwen-test"), provider=provider).handle("双臂抓取")
    assert report.run_status == "blocked"
    assert report.turn_status.value == "clarification_required"
    assert report.clarification_question == "请明确双臂分工"
    assert report.reply == "请明确双臂分工"
    assert report.scene_version is None and "commands" not in report.artifacts
