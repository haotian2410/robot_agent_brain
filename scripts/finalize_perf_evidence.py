#!/usr/bin/env python3
"""Gather local benchmark evidence without exporting credentials or prompts."""
import argparse
import hashlib
import json
import platform
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime",type=Path)
    args=parser.parse_args()
    root=args.runtime
    base=Path(__file__).resolve().parents[1]
    environment=json.loads((base/"var/perf/preflight-20261119-01/environment.json").read_text())
    environment.update(scope="17 real service-submitted turns; Mock and preflight separately labeled",
        cpu="Intel Core i9-14900K",gpu="NVIDIA RTX 4090 D",gpu_memory_mib=24564,
        inference_engine="llama.cpp llama-server",context_size=32768,gpu_layers=999,
        image_min_tokens=1024,reasoning="off",execution_enabled=False,
        shared_services="Qwen8080/OLS8000 shared with other idle integration services; external background activity not fully excluded",
        service_ports={"gateway":8096,"brain":8503},model_cold="not_run",
        instrumentation_note="Real runtime used initial instrumentation; final disk additions for step_index/hash-byte counts verified in Mock/preflight, not silently attributed to earlier real traces")
    diff=subprocess.check_output(["git","diff","--binary"],cwd=base)
    environment["tracked_diff_sha256"]=hashlib.sha256(diff).hexdigest()
    files=[*base.glob("scripts/*perf*.py"),base/"src/robot_agent_brain/perf_trace.py"]
    environment["diagnostic_source_sha256"]={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (root/"environment.json").write_text(json.dumps(environment,ensure_ascii=False,indent=2)+"\n")
    data=json.loads((root/"summary.json").read_text())
    with httpx.Client(timeout=20,trust_env=False) as client:
        for row in data["turns"]:
            response=client.get("http://127.0.0.1:8503/queryTaskResult",params={"taskID":row["task_id"]})
            response.raise_for_status()
            result=response.json()
            # Task result evidence is distinct from spans. Do not include raw prompt/model dump.
            selected={key:result.get(key) for key in ("outcome","executed","reply","error","metrics","artifacts","commitReceipts","scene_commit_status")}
            destination=root/row["batch"]/row["evidence"]/"task_result_evidence.json"
            destination.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+"\n")
    tests={}
    for path in (base/"var/perf").glob("*.xml"):
        xml=ET.parse(path).getroot()
        suites=[xml] if xml.tag=="testsuite" else list(xml.iter("testsuite"))
        tests[path.name]={key:sum(int(s.get(key,0)) for s in suites) for key in ("tests","failures","errors","skipped")}
    (root/"test_results.json").write_text(json.dumps(tests,indent=2)+"\n")
    lines=["# 回归结果", "", "|输出|tests|failures|errors|skipped|", "|---|---:|---:|---:|---:|"]
    lines += [f"|{name}|{r['tests']}|{r['failures']}|{r['errors']}|{r['skipped']}|" for name,r in sorted(tests.items())]
    lines += ["", "全量pytest是兼容性回归，包含仓库原有replay/legacy测试，不是recipe性能对照。实际性能任务配置始终planner=qwen。",
        "", "P11在test_perf_web.py中验证成功与失败任务重发，开/关各运行一次；不增加provider调用，无重复提交。P10独立20对Mock三步骤结果见mock-P10/results.json。",
        "", "真实用例16轮达到预期，P06第二轮失败。P09及真正模型冷启动未测；不能宣称全量真实联调通过。",
        "", "插桩未修改业务处理语义；全量测试通过不代表真实模型一定正确。实际S协议重试和恢复缺字段仍待修复。"]
    (root/"test_results.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(tests))


if __name__=="__main__":
    main()
