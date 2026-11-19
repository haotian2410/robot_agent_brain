#!/usr/bin/env python3
"""Real Web/Gateway/OLS/Qwen diagnostic cases, isolated sessions, no Control.

The service must run with execution_enabled=false. Does not reset Qwen or OLS.
"""
import argparse
import copy
import hashlib
import json
import time
from pathlib import Path

from robot_agent_brain.batch_service import ServiceBatchRunner
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.web.protocol import digest
from analyze_perf_trace import write_outputs


CASES={
    "U-MOVE-CLEAR":("1/ur5_table_empty.json",["在桌面增加一个苹果", "把苹果向右移动五毫米"]),
    "U-FUZZY-CLEAR":("1/ur5_table_empty.json",["在桌面增加一个苹果", "把苹果向右移动一点"]),
    "U-ROTATE-CLEAR":("1/ur5_table_empty.json",["在桌面增加一个苹果", "把苹果绕世界Z轴旋转九十度"]),
    "U-REPLACE-CLEAR":("1/ur5_table_empty.json",["在桌面增加一个苹果", "把苹果替换成一个棒球"]),
    "U-MOVE":("3/ur5_table_sorting.json",["把苹果向右移动五毫米"]),
    "U-FUZZY":("3/ur5_table_sorting.json",["把苹果向右移动一点"]),
    "U-ROTATE":("3/ur5_table_sorting.json",["把苹果绕世界Z轴旋转九十度"]),
    "U-REPLACE":("3/ur5_table_sorting.json",["把苹果替换成一个棒球"]),
    "U-SCALE":("1/ur5_table_empty.json",["在桌面增加一个篮子", "把篮子放大百分之十"]),
    "U-ORIGINAL":("1/ur5_table_empty.json",["在桌面增加一个苹果", "在原始场景中增加一个香蕉"]),
    "U-REJECT":("3/ur5_table_sorting.json",["把苹果放大两倍", "桌面有几个苹果？"]),
    "U-MULTI":("1/ur5_table_empty.json",["在桌面增加两个苹果和一个托盘", "把最左边的苹果改成蓝色", "桌面有几个苹果？"]),
    "P01":("3/ur5_table_sorting.json",["桌面有几个苹果？"]),
    "P02":("3/ur5_table_sorting.json",["把苹果改成蓝色"]),
    "P03":("1/ur5_table_empty.json",["在桌面增加一个苹果"]),
    "P04":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子"]),
    "P05":("1/ur5_table_empty.json",["增加一个苹果，然后增加一个香蕉"]),
    "P06":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","左边的"]),
    "P07":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子"]),
    "P08":("3/ur5_table_sorting.json",["桌面有几个苹果？"]),
    "R02":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","右边的"]),
    "R03":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","不是篮子，是托盘"]),
    "R04":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","两个都要"]),
    "R05":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","算了"]),
    "R06":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","桌面有几个香蕉"]),
    "R08":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","哪个我也不知道"]),
    "R-ID":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","ID 17 的"]),
    "R-COLOR":("3/ur5_table_sorting.json",["让机械臂把苹果放进篮子","红色的"]),
    "S06":("3/ur5_table_sorting.json",["让机械臂把苹果放到托盘里，再把香蕉放到托盘里"]),
    "S07-open":("7/ur5_table_push_pull.json",["让机械臂拉开抽屉"]),
    "S07-close":("7/ur5_table_push_pull.json",["让机械臂关闭抽屉"]),
}


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def find_trace(root, task_id):
    for path in root.glob("*/spans.jsonl"):
        try:
            rows=[json.loads(line) for line in path.read_text().splitlines()]
        except (OSError,ValueError):
            continue
        if any(r.get("tags",{}).get("task_id")==task_id for r in rows):
            return path,rows
    return None,None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime",required=True,type=Path)
    parser.add_argument("--browser-id",required=True)
    parser.add_argument("--cases",default="P01,P02,P03,P04,P05,P06")
    parser.add_argument("--repeat",type=int,default=1)
    parser.add_argument("--label",required=True)
    parser.add_argument("--agent-url",default="http://127.0.0.1:8503")
    parser.add_argument("--gateway-url",default="http://127.0.0.1:8096")
    args=parser.parse_args()
    config=BrainConfig.load(args.runtime/"brain.json")
    if config.execution_enabled or config.planner!="qwen" or config.control_skill_prompt_path() is None:
        raise SystemExit("diagnostic_configuration_invalid")
    root=args.runtime/args.label
    root.mkdir(parents=True,exist_ok=False)
    runner=ServiceBatchRunner(agent_url=args.agent_url,gateway_url=args.gateway_url,
        output_dir=root,browser_id=args.browser_id,task_timeout=600,screenshot_required=False)
    runner.client.headers["X-WebEditor-Browser-ID"]=args.browser_id
    health=runner._request("GET",args.agent_url+"/health").json()
    tasks=health.get("tasks") or {}
    if tasks.get("active_task_id") is not None or tasks.get("queued",0):
        raise SystemExit("existing_task_running")
    results=[]
    try:
        for case in args.cases.split(","):
            filename,instructions=CASES[case]
            for repetition in range(args.repeat):
                directory=root/f"{case}-{repetition+1:02d}"
                directory.mkdir()
                requested=json.loads((Path(config.asset_library_root)/"scenes"/filename).read_text())
                if case=="P06" or case.startswith("R"):
                    apple=copy.deepcopy(next(o for o in requested["objects"] if o["object_name_in_scene"]=="Apple"))
                    apple["object_id_in_scene"]=max(o["object_id_in_scene"] for o in requested["objects"])+1
                    if case=="R-ID":
                        assert all(o["object_id_in_scene"]!=17 for o in requested["objects"])
                        apple["object_id_in_scene"]=17
                    if case=="R-COLOR":
                        mesh=next(c["properties"] for c in apple["components"] if c["component_type"]=="MeshRenderer")
                        mesh["forceOverrideColor"]="#0000FF"
                    apple["object_name_in_scene"]="AppleLeft"
                    transform=next(c["properties"] for c in apple["components"] if c["component_type"]=="Transform")
                    transform["position"][0]-=.2
                    requested["objects"].append(apple)
                fixture=directory/"fixture.json"
                save(fixture,requested)
                try:
                    activation=runner._activate(args.browser_id,requested)
                    sid=activation["sessionID"]
                    world=runner._load_preset(fixture,args.browser_id)
                    for turn,instruction in enumerate(instructions,1):
                        turn_root=directory/f"turn-{turn}"
                        turn_root.mkdir()
                        save(turn_root/"scene_before.json",world)
                        start=time.perf_counter_ns()
                        request_id,accepted=runner._start_task(sid,args.browser_id,instruction,world)
                        task_id=accepted["taskID"]
                        print(json.dumps({"case":case,"repeat":repetition+1,"turn":turn,"task_id":task_id,"state":"running"}),flush=True)
                        state,result=runner._wait_task(task_id)
                        end=time.perf_counter_ns()
                        world=runner._world(args.browser_id)
                        save(turn_root/"scene_after.json",world)
                        save(turn_root/"task_result.json",result)
                        runner._download_artifacts(result, turn_root)
                        camera_id = result.get("camera_id") or activation.get("camera_id")
                        try:
                            if camera_id is None:
                                raise RuntimeError("camera_not_bound")
                            screenshot = runner._capture(args.browser_id, world, turn_root/"screenshot.png", camera_id)
                        except Exception as exc:
                            screenshot = {"status": "blocked", "reason": str(exc)}
                        save(turn_root/"screenshot_metadata.json",screenshot)
                        row={"case":case,"repeat":repetition+1,"turn":turn,"instruction":instruction,
                             "session_id":sid,"task_id":task_id,"client_request_id":request_id,
                             "poll_observed_ms":(end-start)/1e6,"terminal":state.get("terminal"),
                             "outcome":result.get("outcome"),"executed":result.get("executed"),
                             "screenshot":screenshot,
                             "reply":result.get("reply"),"error_code":(result.get("error") or {}).get("code"),
                             "scene_before_digest":digest(json.loads((turn_root/"scene_before.json").read_text())),
                             "scene_after_digest":digest(world),"evidence":str(turn_root.relative_to(root)),
                             "environment":"real_browser_gateway_ols_qwen_no_control",
                             "warmth":"provider first-use or reused; Qwen server already running, not model-cold"}
                        deadline=time.monotonic()+10
                        while True:
                            path,spans=find_trace(args.runtime/"traces",task_id)
                            if spans or time.monotonic()>deadline:
                                break
                            time.sleep(.1)
                        if spans:
                            summary=write_outputs(spans,turn_root)
                            row["trace_file"]=str(path.relative_to(args.runtime))
                            row["trace_ms"]=summary["observed_window_ms"]
                            row["qwen_calls"]=summary["qwen_calls"]
                        else:
                            row["trace_status"]="missing"
                        save(turn_root/"result.json",row)
                        results.append(row)
                        save(root/"results.json",results)
                        print(json.dumps({k:row.get(k) for k in ("case","turn","task_id","outcome","error_code","trace_ms")},ensure_ascii=False),flush=True)
                        if result.get("executed") is True:
                            raise RuntimeError("unexpected_control_execution")
                except Exception as exc:
                    # Record and stop: do not guess whether an interrupted task is safe to abandon.
                    save(directory/"runner_error.json",{"type":type(exc).__name__,"message":str(exc)})
                    raise
    finally:
        runner.client.close()


if __name__=="__main__":
    main()
