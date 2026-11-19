#!/usr/bin/env python3
"""Analyze PerfTrace intervals without summing overlapping sibling wall time.

Adapted from the user's 03_trace_analyzer.py contract. Concurrent leaf spans
remain an explicit combined category; they are not assigned fictitious CPU time.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def percentile(values, q):
    values = sorted(values)
    rank = (len(values)-1)*q
    lo, hi = math.floor(rank), math.ceil(rank)
    return values[lo] + (values[hi]-values[lo])*(rank-lo)


def analyze(records):
    spans = [r for r in records if r.get("type") == "span"]
    if not spans:
        raise ValueError("no_spans")
    ids = {s["span_id"]:s for s in spans}
    if len(ids) != len(spans):
        raise ValueError("duplicate_span_id")
    ancestors = {}
    for s in spans:
        chain, parent = set(), s.get("parent_span_id")
        while parent in ids:
            if parent in chain or parent == s["span_id"]:
                raise ValueError("cyclic_span_parent")
            chain.add(parent)
            parent = ids[parent].get("parent_span_id")
        ancestors[s["span_id"]] = chain
        if s["end_ns"] < s["start_ns"]:
            raise ValueError("negative_span_duration")
    edges = sorted({v for s in spans for v in (s["start_ns"], s["end_ns"])})
    origin, end = edges[0], edges[-1]
    buckets, wall, slices = defaultdict(lambda: defaultdict(float)), defaultdict(float), []
    for a, b in zip(edges, edges[1:]):
        active = [s for s in spans if s["start_ns"] <= a and s["end_ns"] >= b]
        parents = set().union(*(ancestors[s["span_id"]] for s in active)) if active else set()
        leaves = [s for s in active if s["span_id"] not in parents]
        names = sorted({s["name"] for s in leaves})
        label = "unattributed" if not names else names[0] if len(names)==1 else "concurrent:"+"+".join(names)
        sources = sorted({s.get("source", "unknown") for s in leaves})
        wall[label] += (b-a)/1e6
        slices.append({"start_ms":(a-origin)/1e6, "end_ms":(b-origin)/1e6,
                       "stage":label, "sources":sources,
                       "wait_kinds": sorted({s.get("tags",{}).get("wait_kind", "unspecified") for s in leaves})})
        for second in range((a-origin)//10**9, (b-1-origin)//10**9+1):
            overlap = min(b, origin+(second+1)*10**9)-max(a,origin+second*10**9)
            if overlap > 0:
                buckets[second][label] += overlap/1e6
    stages = defaultdict(list)
    for s in spans:
        stages[s["name"]].append((s["end_ns"]-s["start_ns"])/1e6)
    summary = {
        "trace_id":spans[0]["trace_id"], "span_count":len(spans),
        "observed_window_ms":(end-origin)/1e6,
        "wall_time_partition_ms":dict(sorted(wall.items(),key=lambda x:-x[1])),
        "wall_partition_note":"Non-overlapping observed intervals; concurrent leaf stages remain combined. Not CPU time or a proven distributed critical path.",
        "stage_summary":[{"name":name,"count":len(values),"inclusive_sum_ms":sum(values),
            "p50_ms":percentile(values,.5),"p90_ms":percentile(values,.9),"p95_ms":percentile(values,.95),
            "max_ms":max(values),"p95_reliable":len(values)>=20} for name,values in stages.items()],
        "unattributed_over_500ms":[s for s in slices if s["stage"]=="unattributed" and s["end_ms"]-s["start_ms"]>500],
        "qwen_calls":[{"duration_ms":(s["end_ns"]-s["start_ns"])/1e6,**s.get("tags",{})}
                      for s in spans if s["name"]=="qwen.http_wait"],
        "top10_spans":[{"name":s["name"],"source":s.get("source"),"duration_ms":(s["end_ns"]-s["start_ns"])/1e6}
                       for s in sorted(spans,key=lambda s:s["end_ns"]-s["start_ns"],reverse=True)[:10]],
    }
    executed = [s for s in spans if s["name"] == "web.execute"]
    summary["submit_to_execute_end_ms"] = ((max(s["end_ns"] for s in executed)-origin)/1e6 if executed else None)
    summary["terminal_timing_note"] = "Execution-end proxy; poll_observed_ms includes polling latency. Playback is separately timed."
    summary["queue_wait_ms"] = sum(stages.get("web.queue.wait", []))
    summary["playback_upload_ms"] = sum(stages.get("web.playback_upload", []))
    summary["ols_http_requests"] = sum(len(stages.get(n, [])) for n in ("ols.check_list", "ols.check_item"))
    summary["gateway_http_requests"] = len(stages.get("gateway.http_wait", []))
    summary["checkpoint_count"] = len(stages.get("store.save", []))
    rows = []
    for second in range(math.ceil((end-origin)/1e9)):
        values = buckets[second]
        ranked = sorted(values,key=values.get,reverse=True)
        rows.append(dict(second_index=second,active_leaf_stages=json.dumps(values,ensure_ascii=False),
                         dominant_stage=ranked[0] if ranked else "unattributed",
                         confidence="observed_intervals_not_cpu"))
    return summary, rows, slices


def write_outputs(records, output):
    summary, rows, slices = analyze(records)
    output.mkdir(parents=True, exist_ok=True)
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    (output/"timeline.json").write_text(json.dumps(slices,ensure_ascii=False,indent=2)+"\n")
    with (output/"timeline_seconds.csv").open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["second_index","active_leaf_stages","dominant_stage","confidence"])
        writer.writeheader()
        writer.writerows(rows)
    lines=[f"trace_id: {summary['trace_id']}","Intervals are observed wall time, not CPU samples.",""]
    lines += [f"{s['start_ms']/1000:.6f}–{s['end_ms']/1000:.6f}s {s['stage']} | {', '.join(s['sources'])} | {s['wait_kinds']}" for s in slices]
    lines += ["", "Per-second:"]+[f"[{r['second_index']}–{r['second_index']+1}s] {r['active_leaf_stages']}" for r in rows]
    (output/"timeline.txt").write_text("\n".join(lines)+"\n")
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spans",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    traces=defaultdict(list)
    for line in args.spans.read_text().splitlines():
        record=json.loads(line)
        if record.get("type")=="span":
            traces[record["trace_id"]].append(record)
    if len(traces)!=1:
        raise SystemExit("Expected exactly one trace per file")
    write_outputs(next(iter(traces.values())),args.out)


if __name__=="__main__":
    main()
