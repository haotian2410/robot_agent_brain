"""Independent semantic audit and paired timings for the U-only benchmark."""
import argparse
import json
from pathlib import Path
import statistics


def audit(case, value):
    if case == "clarification":
        return value["status"] == "clarification_required" and bool(value.get("clarification_question")) and all(
            not value.get(k) for k in ["scene_edit", "scene_query", "task_intent", "robot_asset_switch"])
    if value["status"] != "accepted":
        return False
    payload = value.get("scene_edit") or value.get("scene_query") or value.get("task_intent") or {}
    entities = payload.get("entities", [])
    names = {e["entity_id"]: e["semantic_name"] for e in entities}
    if any(e.get("scene_object_ids") or e.get("exclude_scene_object_ids") for e in entities):
        return False  # no test instruction contains explicit IDs or exclusions
    counts = {e["semantic_name"]: e["count"] for e in entities}
    if case in {"robot", "recovered"}:
        ops = payload.get("operations", [])
        if counts != {"apple": 1, "basket": 1} or len(ops) != 1:
            return False
        op = ops[0]; target = op.get("placement_target") or {}
        valid = (op.get("task_type") == "pick_and_place" and names.get(op.get("source")) == "apple"
                 and names.get(op.get("destination")) == "basket" and target.get("kind") == "container_interior"
                 and names.get(target.get("reference")) == "basket" and target.get("relation") == "inside")
        relations = payload.get("spatial_relations", [])
        return valid and (not relations if case == "robot" else bool(relations) and all(
            r["relation"] == "leftmost" and names.get(r["subject"]) == "apple" and not r.get("reference")
            for r in relations))  # duplicate identical constraints are semantically idempotent
    if case == "query":
        return (value["turn_kind"] == "scene_query" and payload.get("query_type") == "relation"
                and names.get(payload.get("target")) == "apple" and names.get(payload.get("reference")) == "basket"
                and payload.get("predicate") == "left_of")
    if value["turn_kind"] != "scene_edit" or payload.get("scene_basis") != "current":
        return False
    ops = payload.get("operations", [])
    if case == "color":
        return (counts == {"apple": 1} and len(ops) == 1 and ops[0]["operation"] == "update_properties"
                and names.get(ops[0]["target"]) == "apple" and ops[0]["properties"].get("color") in
                {"blue", "蓝色", "#0000FF", "#0000ff"} and set(ops[0]["properties"]) == {"color"})
    choices = {names.get(c["entity_id"]): c["asset_key"] for c in payload.get("asset_choices", [])}
    return (counts == {"apple": 2, "tray": 1} and len(ops) == 2
            and {names.get(o["target"]) for o in ops} == {"apple", "tray"}
            and all(o["operation"] == "add" and o["relation"] == "on" and o["reference"] == "table" for o in ops)
            and choices == {"apple": "model:1", "tray": "model:17"})


def stats(rows):
    def numbers(key):
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)} if values else None
    return {"n": len(rows), "valid": sum(r["valid"] for r in rows),
            "semantic_pass": sum(r["semantic_pass"] for r in rows),
            "retries": sum(max(0, r["calls"] - 1) for r in rows),
            **{k: numbers(k) for k in ["seconds", "prompt_tokens", "completion_tokens", "input_seconds", "output_seconds", "cached_tokens"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    rows = json.loads((args.root / "results.json").read_text())
    for row in rows:
        directory = args.root / f'{row["case"]}-{row["repeat"]}-{row["group"]}'
        canonical = directory / "canonical.json"
        row["semantic_pass"] = bool(row["valid"] and canonical.exists() and audit(row["case"], json.loads(canonical.read_text())))
        calls = json.loads((directory / "calls.json").read_text())
        timings = [c.get("server_timings") for c in calls]
        if all(t and "prompt_ms" in t and "predicted_ms" in t for t in timings):
            row["input_seconds"] = sum(t["prompt_ms"] for t in timings) / 1000
            row["output_seconds"] = sum(t["predicted_ms"] for t in timings) / 1000
            row["cached_tokens"] = sum(t.get("cache_n", 0) for t in timings)
        row["evidence"] = str(directory.resolve())
    groups = sorted({r["group"] for r in rows})
    report = {"complete": len(rows) == len(json.loads((args.root / "schedule.json").read_text())),
              "scope": "U only; no lease, Scene commits or Control; recovered is the resolved instruction supplied to U, not a full R replay",
              "groups": {g: stats([r for r in rows if r["group"] == g]) for g in groups},
              "cases": {c: {g: stats([r for r in rows if r["case"] == c and r["group"] == g]) for g in groups}
                        for c in sorted({r["case"] for r in rows})},
              "first_calls": {g: stats([r for r in rows if r["group"] == g and r["first_provider_call"]]) for g in groups},
              "cache_reused": {g: stats([r for r in rows if r["group"] == g and r.get("cached_tokens", 0) > 0]) for g in groups},
              "cache_miss": {g: stats([r for r in rows if r["group"] == g and r.get("cached_tokens") == 0]) for g in groups},
              "failures": [r for r in rows if not r["semantic_pass"]], "rows": rows}
    baseline = report["groups"].get("baseline")
    if baseline:
        report["median_reduction_vs_baseline_pct"] = {
            g: {key: round(100 * (1 - report["groups"][g][key]["median"] / baseline[key]["median"]), 2)
                for key in ("prompt_tokens", "completion_tokens", "seconds")}
            for g in groups if g != "baseline"}
    (args.root / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["U 资产目录去重与紧凑输出：真实模型对照", f'完成：{report["complete"]}；当前 {len(rows)} 轮', report["scope"],
             "耗时单位：秒。输入/输出计算来自同一 HTTP 响应 timings；不包含在客户端总耗时外重复相加。", ""]
    for group, data in report["groups"].items():
        lines.append(f'{group}: {json.dumps(data, ensure_ascii=False)}')
    lines.append("\n逐用例中位数：case | group | 输出tokens | U总时间 | 输入计算 | 输出生成 | 语义通过")
    for case, values in report["cases"].items():
        for group, data in values.items():
            def median(k): return round(data[k]["median"], 3) if data[k] else "未采集"
            lines.append(f'{case} | {group} | {median("completion_tokens")} | {median("seconds")} | {median("input_seconds")} | {median("output_seconds")} | {data["semantic_pass"]}/{data["n"]}')
    lines.append("\n未通过：" + json.dumps(report["failures"], ensure_ascii=False))
    (args.root / "report.txt").write_text("\n".join(lines) + "\n")
    print(json.dumps({g: report["groups"][g] for g in groups}, ensure_ascii=False))


if __name__ == "__main__":
    main()
