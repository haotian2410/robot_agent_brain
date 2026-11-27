import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit_report", Path(__file__).resolve().parents[1]
                                            / "scripts/report_layout_dual_audit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_report_preserves_retries_missing_times_and_historical_category(tmp_path):
    task = tmp_path / "session" / "task"
    task.mkdir(parents=True)
    raw = {"request_id": "task", "session_id": "session", "run_status": "failed",
           "error": {"code": "scene_layout_capacity_exceeded", "category": "semantic_protocol"},
           "metrics": {"model_calls": [
               {"stage": "task_understanding", "status": "failed", "usage": {"prompt_tokens": 0}},
               {"stage": "task_understanding", "status": "succeeded", "completion_tokens": 5,
                "server_timings": {"prompt_ms": 1200, "predicted_ms": 3000, "cache_n": 0}}]}}
    path = task / "result.json"
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    report = module.compile_report(tmp_path)
    value = report["tasks"][0]
    assert value["classification"] == "geometry_safe_refusal"
    assert value["error"]["category"] == "semantic_protocol"
    assert value["model_call_count"] == 2
    assert value["calls"][0]["input_tokens"] == 0
    assert value["calls"][0]["input_compute_seconds"] is None
    assert value["calls"][1]["input_compute_seconds"] == 1.2
    assert value["calls"][1]["output_generate_seconds"] == 3
    assert path.read_bytes() == before
    assert "未采集" in module.markdown(report)


def test_bad_report_is_reported_not_silently_dropped(tmp_path):
    task = tmp_path / "session" / "task"
    task.mkdir(parents=True)
    (task / "result.json").write_text("{")
    report = module.compile_report(tmp_path)
    assert len(report["read_errors"]) == 1
    assert not report["tasks"]


def test_report_success_never_claims_independent_acceptance():
    assert module.classify({"run_status": "success"}) == "reported_success_not_independent_acceptance"


def test_runtime_and_gateway_failures_are_not_automatically_blame_model():
    assert module.classify({"error": {"code": "validation_failed", "stage": "processing"}}) == "runtime_validation_failure_requires_diagnosis"
    assert module.classify({"error": {"code": "gateway_commit_readback_mismatch"}}) == "scene_sync_failure"
