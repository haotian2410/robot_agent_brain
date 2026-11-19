#!/usr/bin/env python3
"""Summarize completed optimization experiments without treating gaps as passes."""
import argparse
import csv
import json
import statistics
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases, calls, stats = [], [], []
    trace_files=set()
    timelines=[]
    for group in sorted(args.runtime.glob("optimization-*")):
        if not group.is_dir():
            continue
        records = []
        for path in sorted(group.glob("*/turn-*/result.json")):
            row = json.loads(path.read_text())
            if row.get("trace_file"):
                trace_files.add(args.runtime/row["trace_file"])
            if (path.parent/"timeline.txt").is_file():
                timelines.append(f"\n===== {group.name} task {row['task_id']} =====\n"+(path.parent/"timeline.txt").read_text())
            models = row.get("qwen_calls", [])
            detail_path=path.parent/"task_result_evidence.json"
            details=json.loads(detail_path.read_text()).get("metrics",{}).get("model_call_details",[]) if detail_path.exists() else []
            detail_by_stage={stage:[m for m in details if m.get("stage")==stage]
                for stage in {m.get("stage") for m in models}}
            indices={stage:0 for stage in detail_by_stage}
            skills = [m for m in models if m.get("stage") == "skill_planning"]
            summary_path=path.parent/"summary.json"
            summary=json.loads(summary_path.read_text()) if summary_path.exists() else {}
            partition=summary.get("wall_time_partition_ms",{})
            stage_counts={s["name"]:s["count"] for s in summary.get("stage_summary",[])}
            item = {"group":group.name, "case":row["case"], "repeat":row["repeat"],
                "turn":row["turn"], "task_id":row["task_id"], "outcome":row["outcome"],
                "error_code":row.get("error_code"), "wall_ms":row.get("trace_ms"),
                "model_calls":len(models), "s_calls":len(skills),
                "s_first_pass":bool(len(skills)==1 and row["outcome"]=="plan_ready"),
                "prompt_tokens":sum(m.get("prompt_tokens",0) or 0 for m in models),
                "completion_tokens":sum(m.get("completion_tokens",0) or 0 for m in models),
                "ols_http_requests":stage_counts.get("ols.check_item",0)+stage_counts.get("ols.check_list",0),
                "ols_http_ms":partition.get("ols.check_item",0)+partition.get("ols.check_list",0),
                "local_asset_hash_ms":partition.get("ols.cache_hash.files",0),
                "qwen_http_ms":partition.get("qwen.http_wait",0),
                "gateway_http_ms":partition.get("gateway.http_wait",0),
                "store_ms":partition.get("store.save",0)+partition.get("store.load",0),
                "scene_unchanged":row.get("scene_before_digest")==row.get("scene_after_digest"),
                "evidence":str(path.resolve())}
            cases.append(item)
            records.append(item)
            for i,m in enumerate(models):
                detail={}
                stage=m.get("stage")
                stage_details=detail_by_stage.get(stage,[])
                if len(stage_details)==sum(c.get("stage")==stage for c in models):
                    detail=stage_details[indices[stage]]
                    indices[stage]+=1
                calls.append({"group":group.name, "task_id":row["task_id"], "call":i+1,
                    **{key:m.get(key) for key in ("stage","duration_ms","retry_index","retry_reason",
                        "prompt_tokens","completion_tokens","finish_reason","skill_md_sha256")},
                    "http_span_status":m.get("status"),"semantic_status":detail.get("status","not_joined"),
                    "prompt_hash":detail.get("prompt_sha256"),"schema_hash":detail.get("schema_sha256")})
        for case in sorted({r["case"] for r in records}):
            for turn in sorted({r["turn"] for r in records if r["case"]==case}):
                selected = [r for r in records if r["case"]==case and r["turn"]==turn]
                stats.append({"group":group.name,"case":case,"turn":turn,"n":len(selected),
                    "median_ms":statistics.median(r["wall_ms"] for r in selected),
                    "outcomes":{v:sum(r["outcome"]==v for r in selected) for v in sorted({r["outcome"] for r in selected})},
                    "model_calls":sorted({r["model_calls"] for r in selected}),
                    "s_first_pass":sum(r["s_first_pass"] for r in selected)})
    for name, rows in (("cases.csv", cases), ("model_calls.csv", calls)):
        if rows:
            with (args.output/name).open("w", newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    (args.output/"phase_summary.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2)+"\n")
    with (args.output/"spans.jsonl").open("w") as stream:
        for path in sorted(trace_files):
            if path.is_file():
                stream.write(path.read_text().rstrip()+"\n")
    (args.output/"timeline.txt").write_text("".join(timelines))
    ab=[]
    for case in ("P01","P04"):
        selected={v:[r for r in cases if re.fullmatch(f"optimization-ab-{v}[0-9]+",r["group"]) and r["case"]==case] for v in ("A","B")}
        if not all(selected.values()):
            continue
        row={"case":case,"A_n":len(selected["A"]),"B_n":len(selected["B"])}
        for v,items in selected.items():
            row[v+"_median_ms"]=statistics.median(r["wall_ms"] for r in items)
            row[v+"_s_first_pass"]=sum(r["s_first_pass"] for r in items)
            row[v+"_outcomes"]={k:sum(r["outcome"]==k for r in items) for k in sorted({r["outcome"] for r in items})}
        row["median_change_percent"]=(row["B_median_ms"]/row["A_median_ms"]-1)*100
        row["complete_ten_pairs"]=row["A_n"]==row["B_n"]==10
        ab.append(row)
    (args.output/"ab_summary.json").write_text(json.dumps(ab,ensure_ascii=False,indent=2)+"\n")
    lines=["# 分阶段实测", "", "只统计已有终态证据；此表不是全量通过声明，最终判定见report.md和acceptance.md。",
        "阶段实验顺序运行；optimization-ab-*为固定seed的交替AB。共享Qwen/OLS，外部负载未完全排除。每组少于20不报告p95。", "",
        "|阶段|用例/轮次|样本数|中位数秒|结果|模型调用数|S首答通过|", "|---|---|---:|---:|---|---|---:|"]
    for row in stats:
        lines.append(f"|{row['group']}|{row['case']}/{row['turn']}|{row['n']}|{row['median_ms']/1000:.3f}|{row['outcomes']}|{row['model_calls']}|{row['s_first_pass']}|")
    lines += ["", "S首答只依据单次S调用且plan_ready统计，仍须独立核对完整Commands和对象身份；HTTP成功不是语义成功。",
        "OLS仍完整核验，快照不可复用；Control执行与真正模型冷启动为not_run。"]
    lines += ["", "## 交替AB汇总", "", "只有complete_ten_pairs=true才达到本次样本门槛。"]
    lines += ["", "```json",json.dumps(ab,ensure_ascii=False,indent=2),"```"]
    (args.output/"before_after.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(stats,ensure_ascii=False))


if __name__ == "__main__":
    main()
