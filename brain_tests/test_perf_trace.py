import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from robot_agent_brain.perf_trace import span, timed, trace_scope


def test_disabled_has_no_files_or_changed_result(tmp_path, monkeypatch):
    monkeypatch.delenv("ROBOT_BRAIN_PERF_TRACE", raising=False)
    @timed("test.call")
    def call(value):
        return value
    value = object()
    with trace_scope(output_dir=tmp_path) as trace:
        assert trace is None
        assert call(value) is value
    assert list(tmp_path.iterdir()) == []


def test_nested_spans_exception_and_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_BRAIN_PERF_TRACE", "1")
    error = ValueError("secret exception text")
    with pytest.raises(ValueError) as caught:
        with trace_scope("../outside", output_dir=tmp_path) as trace:
            with span("parent", source="module:parent"):
                with span("child", prompt="secret", api_key="secret", prompt_chars=12,
                          retry_reason="/private/secret"):
                    raise error
    assert caught.value is error
    records = [json.loads(line) for line in trace.path.read_text().splitlines()]
    child, parent = records
    assert child["parent_span_id"] == parent["span_id"]
    assert child["tags"] == {"prompt_chars":12, "error_type":"ValueError"}
    assert child["status"] == parent["status"] == "error"
    assert parent["start_ns"] <= child["start_ns"] <= child["end_ns"] <= parent["end_ns"]
    assert "secret" not in trace.path.read_text()
    assert trace.path.is_relative_to(tmp_path)


def test_to_thread_preserves_parent_and_async_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_BRAIN_PERF_TRACE", "1")
    @timed("thread.call")
    def child():
        return 7
    @timed("async.call")
    async def parent():
        return await asyncio.to_thread(child)
    with trace_scope(output_dir=tmp_path) as trace:
        assert asyncio.run(parent()) == 7
    child_row, parent_row = trace.records
    assert child_row["parent_span_id"] == parent_row["span_id"]
    assert child_row["thread_id"] != parent_row["thread_id"]


def test_output_failure_does_not_change_business_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_BRAIN_PERF_TRACE", "1")
    target = tmp_path / "file"
    target.write_text("preserve")
    with trace_scope(output_dir=target) as trace:
        with span("test"):
            result = 42
    assert result == 42
    assert trace.output_error is not None
    assert target.read_text() == "preserve"


def test_concurrent_roots_do_not_mix(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_BRAIN_PERF_TRACE", "1")
    def run(identifier):
        with trace_scope(identifier, output_dir=tmp_path) as trace:
            with span("work"):
                pass
        return trace
    with ThreadPoolExecutor(2) as pool:
        traces = list(pool.map(run, ["one", "two"]))
    assert {t.records[0]["trace_id"] for t in traces} == {"one", "two"}
    assert all(t.records[0]["parent_span_id"] is None for t in traces)


def test_qwen_trace_reuses_usage_and_does_not_change_payload(tmp_path, monkeypatch):
    import httpx
    from robot_agent_brain.models.qwen_http import QwenHTTPProvider
    from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({"status":"accepted",
                "turn_kind":"session_control", "session_control":{"action":"pause"}})}, "finish_reason":"stop"}],
            "usage":{"prompt_tokens":10, "completion_tokens":5, "total_tokens":15}})
    for enabled in ("0", "1"):
        monkeypatch.setenv("ROBOT_BRAIN_PERF_TRACE", enabled)
        with trace_scope(output_dir=tmp_path) as trace:
            provider = QwenHTTPProvider("http://mock/v1", "test", api_key="private-key",
                transport=httpx.MockTransport(handler), atomic_skill_prompt_path=str(tmp_path / "missing"), understanding_wire_format="full")
            result = provider.understand_turn(TaskUnderstandingRequest(instruction="pause"))
            assert result.turn_kind == "session_control"
            assert len(provider.calls) == 1
    assert requests[0] == requests[1]
    waits = [r for r in trace.records if r["name"] == "qwen.http_wait"]
    assert len(waits) == 1
    assert waits[0]["tags"]["total_tokens"] == provider.calls[0]["total_tokens"] == 15
    assert next(r for r in trace.records if r["name"] == "planning.skill_prompt.load")["tags"]["skill_prompt_source"] == "bundled_fallback"
    assert "private-key" not in trace.path.read_text()
