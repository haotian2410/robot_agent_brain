#!/usr/bin/env python3
"""Aggregate measured cases without treating nested timings as additive."""
import argparse
import collections
import json
import statistics
from pathlib import Path
from analyze_perf_trace import write_outputs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("runtime",type=Path)
    args=p.parse_args()
    root=args.runtime
    rows=[]
    for result_file in sorted(root.glob("*/results.json")):
        values=json.loads(result_file.read_text())
        if not isinstance(values,list):
            continue
        for row in values:
            trace=row.get("trace_file")
            if not trace:
                continue
            records=[json.loads(s) for s in (root/trace).read_text().splitlines()]
            summary=write_outputs(records,result_file.parent/row["evidence"])
            expected={"P01":"answered","P02":"scene_updated","P03":"scene_updated",
                      "P04":"plan_ready","P05":"scene_updated","P07":"plan_ready","P08":"answered"}
            wanted=expected.get(row["case"],"clarification_required" if row["turn"]==1 else "plan_ready")
            row={**row,"batch":result_file.parent.name,"status":"pass" if row["outcome"]==wanted else "fail",
                 "summary":summary}
            rows.append(row)
    totals=collections.Counter()
    for row in rows:
        totals.update(row["summary"]["wall_time_partition_ms"])
    grouped={}
    for case in sorted({r["case"] for r in rows}):
        sample=[r for r in rows if r["case"]==case]
        grouped[case]={"runs":len(sample),"pass":sum(r["status"]=="pass" for r in sample),
            "fail":sum(r["status"]=="fail" for r in sample),
            "median_s":statistics.median(r["trace_ms"] for r in sample)/1000,
            "p95":"not reported: fewer than 20 comparable trials"}
    aggregate={"cases":grouped,"turns":rows,"wall_partition_ms":dict(totals.most_common()),
        "model_cold_status":"not_run: shared Qwen server left running",
        "control_status":"not_run: execution disabled",
        "timing_note":"Trace window includes separately reported playback; not browser perceived latency. HTTP waits include client setup in first-pass/warm-five instrumentation."}
    (root/"summary.json").write_text(json.dumps(aggregate,ensure_ascii=False,indent=2)+"\n")
    lines=["# Brain 性能诊断测量汇总", "", "真实浏览器绑定 + Gateway/OLS/Qwen；通过 Brain /startTask 提交，不是 UI 点击计时。planner=qwen，execution_enabled=false。", "",
        "|批次|用例/轮次|task|结果|耗时(s)|OLS HTTP|checkpoint|Qwen调用|",
        "|---|---|---|---|---:|---:|---:|---|"]
    for r in rows:
        s=r["summary"]
        calls=collections.Counter(c["stage"] for c in s["qwen_calls"])
        lines.append(f"|{r['batch']}|{r['case']}/{r['turn']}|{r['task_id']}|{r['status']}: {r['outcome']}|{r['trace_ms']/1000:.3f}|{s['ols_http_requests']}|{s['checkpoint_count']}|{dict(calls)}|")
    lines += ["", "## 不重叠墙钟时间分布", "", "下表不是 CPU 时间；父子 span 没有重复相加。"]
    total=sum(totals.values())
    lines += [f"- `{k}`：{v/1000:.3f}s，{v/total*100:.2f}%" for k,v in totals.most_common(10)]
    lines += ["", "## 逐秒证据", ""]
    for r in sorted(rows,key=lambda r:-r["trace_ms"])[:3]:
        path=Path(r["batch"])/r["evidence"]
        lines.append(f"- task {r['task_id']}：[{r['case']} timeline]({path}/timeline.txt)，[逐秒 CSV]({path}/timeline_seconds.csv)。")
    lines += ["", "## 限制", "", "- 模型服务器未重启：不能把首轮称为模型冷启动。", "- 每类5次样本不足以报告可靠 p95。", "- Qwen HTTP 等待不等于纯推理时间；没有关联服务器 request ID 的 prefill/decode 指标，不报告虚构 tokens/s。", "- P06 恢复失败为实际功能失败，场景摘要未改变；本轮不修改业务逻辑。", "- 控制端未调用，不评价 Control 内部性能或真实执行效果。"]
    (root/"summary.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(grouped,ensure_ascii=False))


if __name__=="__main__":
    main()
