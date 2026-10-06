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
