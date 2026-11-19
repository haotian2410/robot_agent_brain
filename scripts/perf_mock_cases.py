#!/usr/bin/env python3
"""Diagnostic Mock composite benchmark; no network/model/Control execution."""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain_tests"))
from test_composite_orchestrator import Browser, Split, THREE, LEFT, RIGHT, COUNT, THREE_SENTENCE, adapter
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.web.service import AgentService
from robot_agent_brain.web.protocol import SessionRequest, StartTask, digest
from robot_agent_brain.perf_trace import trace_scope
from analyze_perf_trace import write_outputs


def run(root, flag):
    os.environ["ROBOT_BRAIN_PERF_TRACE"] = flag
    browser, provider = Browser(), Split(THREE, [LEFT, RIGHT, COUNT])
    service = AgentService(BrainConfig(provider="replay", planner="qwen", scene_id_bits=32,
        scene_platform_object_ids={0}, output_dir=str(root / "tasks"), debug=True), provider=provider,
        platform_factory=lambda b: adapter(browser, root / b["id"] / "journal"))
    sid = service.activate(SessionRequest(browserID="b"))["sessionID"]
    record, _ = service.tasks.submit(StartTask(command=THREE_SENTENCE, scene=browser.scene,
        sessionID=sid, clientRequestID="composite", browserID="b", sceneDigest=digest(browser.scene)))
    start = time.perf_counter_ns()
    with trace_scope("P10-mock", output_dir=root / "traces") as trace:
        service.execute(record["id"])
    elapsed = (time.perf_counter_ns()-start)/1e6
    result = service.tasks.get(record["id"])["result"]
    assert result["outcome"] == "scene_updated" and result["executed"] is False
    assert provider.splits == 1 and len(provider.asked) == 3
    assert browser.calls.count(("POST", "/commitWorld")) == 2
    if trace:
        write_outputs(trace.records, root)
    return {"elapsed_ms":elapsed,"scene":browser.scene.model_dump(mode="json"),
            "outcome":result["outcome"],"commits":2,"mock_D_calls":1,"mock_U_calls":3}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--pairs",type=int,default=20)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    rows=[]
    for index in range(args.pairs+2):
        pair={}
        for flag in (["0","1"] if index%2==0 else ["1","0"]):
            pair[flag]=run(args.output/f"pair-{index:02d}-{flag}",flag)
        assert pair["0"]["scene"] == pair["1"]["scene"]
        if index>=2:
            rows.append({"off_ms":pair["0"]["elapsed_ms"],"on_ms":pair["1"]["elapsed_ms"]})
    off=statistics.median(r["off_ms"] for r in rows)
    on=statistics.median(r["on_ms"] for r in rows)
    result={"case":"P10","status":"pass","environment":"Mock provider and Gateway; no Control",
            "planner":"qwen","pairs":rows,"off_median_ms":off,"on_median_ms":on,
            "median_overhead_percent":(on/off-1)*100,
            "note":"Includes trace flush, excludes analysis; filesystem/cache noise and instrumentation overhead are both included."}
    (args.output/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="pairs"}))


if __name__=="__main__":
    main()
