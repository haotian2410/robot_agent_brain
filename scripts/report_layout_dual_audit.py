"""Summarize saved Brain task evidence; never run tasks or change their results."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


GEOMETRY = {"scene_layout_capacity_exceeded", "scene_layout_collision",
            "scene_layout_workspace_exceeded"}


def classify(report):
    code = (report.get("error") or {}).get("code", "")
    if code in GEOMETRY:
        return "geometry_safe_refusal"
    if code.startswith(("gateway_", "browser_")) or code == "scene_patch_scene_mismatch":
        return "scene_sync_failure"
    if code == "validation_failed" and (report.get("error") or {}).get("stage") == "processing":
        return "runtime_validation_failure_requires_diagnosis"
    if code == "unsupported_protocol_version" or code.startswith("capability_"):
        return "capability_unsupported"
    if code.startswith(("grounding_", "scene_reference_", "scene_layout_region_")):
        return "reference_or_selection_failure"
    if report.get("turn_status") == "clarification_required":
        return "clarification_required"
    if report.get("run_status") == "success":
        return "reported_success_not_independent_acceptance"
    if code.startswith(("provider_", "semantic_", "task_understanding_")):
        return "model_or_protocol_failure"
    return "unclassified_failure"


def summarize(path):
    raw = path.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict) or "run_status" not in report or "request_id" not in report:
        raise ValueError("not_a_brain_task_report")
    request = path.parent / "request_record.json"
    record = json.loads(request.read_text()) if request.exists() else {}
    metrics = report.get("metrics") or {}
    calls = []
    for index, call in enumerate(metrics.get("model_calls") or [], 1):
        usage = call.get("usage") or {}
        timings = call.get("server_timings") or {}
        calls.append({"index": index, "stage": call.get("stage"), "status": call.get("status"),
            "request_id": call.get("request_id"), "prompt_sha256": call.get("prompt_sha256"),
            "schema_sha256": call.get("schema_sha256"), "wire_format": call.get("wire_format"),
            "input_tokens": call.get("prompt_tokens", usage.get("prompt_tokens")),
            "output_tokens": call.get("completion_tokens", usage.get("completion_tokens")),
            "elapsed_seconds": call.get("elapsed_seconds"),
            "input_compute_seconds": timings["prompt_ms"] / 1000 if timings.get("prompt_ms") is not None else None,
            "output_generate_seconds": timings["predicted_ms"] / 1000 if timings.get("predicted_ms") is not None else None,
            "cached_tokens": timings.get("cache_n")})
    return {"session_id": report.get("session_id"), "task_id": report["request_id"],
        "instruction": record.get("instruction"), "turn_kind": report.get("turn_kind"),
        "run_status": report["run_status"], "classification": classify(report),
        "error": report.get("error"), "scene_commit_status": report.get("scene_commit_status"),
        "scene_id": report.get("scene_id"), "scene_version": report.get("scene_version"),
        "executed": report.get("executed"), "pipeline_seconds": metrics.get("elapsed_seconds"),
        "model_call_count": len(calls), "calls": calls,
        "evidence_directory": str(path.parent.resolve()), "result_sha256": hashlib.sha256(raw).hexdigest()}


def compile_report(root):
    tasks, errors = [], []
    for path in sorted(root.glob("*/*/result.json")):
        try:
            tasks.append(summarize(path))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            errors.append({"path": str(path.resolve()), "error": str(exc)})
    return {"source": str(root.resolve()), "scope": "saved_task_reports_only",
        "limitations": ["Success is the service report, not independent geometry/visual acceptance.",
            "No counterfactual cold-cache comparison; missing timing stays null, not zero.",
            "Historical error categories are retained; classification is a separate audit field.",
            "Retries remain separate tasks; every recorded model call is retained."],
        "counts": dict(Counter(t["classification"] for t in tasks)), "tasks": tasks, "read_errors": errors}


def markdown(report):
    def cell(value):
        return "未采集" if value is None else str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# 布局与双臂任务证据汇总", "", "仅汇总服务记录；成功不等于独立几何、浏览器或控制验收。", "",
             "| Session / task | 指令 | 分类 | Scene提交 | 模型调用 | 总耗时(s) | 证据 |",
             "|---|---|---|---|---|---|---|"]
    for task in report["tasks"]:
        values = [task['session_id'] + '/' + task['task_id'], task['instruction'], task['classification'],
                  task['scene_commit_status'], task['model_call_count'], task['pipeline_seconds'],
                  f"[目录]({task['evidence_directory']})"]
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    lines += ["", "## 逐次模型调用", "", "| Task | 次数/阶段 | 状态 | 输入token | 输出token | 输入计算(s) | 输出生成(s) | 调用总耗时(s) | 缓存token |",
              "|---|---|---|---|---|---|---|---|---|"]
    for task in report["tasks"]:
        for call in task["calls"]:
            values = [task['task_id'], f"{call['index']}/{call['stage']}", call['status'], call['input_tokens'],
                      call['output_tokens'], call['input_compute_seconds'], call['output_generate_seconds'],
                      call['elapsed_seconds'], call['cached_tokens']]
            lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    lines += ["", "## 读取错误", "", json.dumps(report["read_errors"], ensure_ascii=False), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if not args.tasks_root.is_dir():
        parser.error("tasks-root must exist")
    report = compile_report(args.tasks_root)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (args.output_dir / "report.md").write_text(markdown(report))
    print(json.dumps({"counts": report["counts"], "read_errors": len(report["read_errors"])}))
    return int(bool(report["read_errors"]) or not report["tasks"])


if __name__ == "__main__":
    raise SystemExit(main())
