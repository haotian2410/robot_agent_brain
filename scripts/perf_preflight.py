#!/usr/bin/env python3
"""Read-only performance preflight: no tasks, leases, Control or OLS writes."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.perf_trace import span, trace_scope
from robot_agent_brain.web.assets import check_ols
from analyze_perf_trace import write_outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",required=True,type=Path)
    parser.add_argument("--ols-url",default="http://127.0.0.1:8000")
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    config=BrainConfig.load(args.config)
    if config.planner != "qwen":
        raise SystemExit("preflight_requires_planner_qwen")
    skill=config.control_skill_prompt_path()
    if skill is None:
        raise SystemExit("preflight_requires_control_skill_md")
    skill_sha=hashlib.sha256(Path(skill).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    os.environ["ROBOT_BRAIN_PERF_TRACE"]="1"
    environment={"time_utc":datetime.now(timezone.utc).isoformat(),"python":sys.version,
        "platform":platform.platform(),"cpu_count":os.cpu_count(),"planner":config.planner,
        "skill_source":"control/atomic_skill/skill.md", "skill_md_sha256":skill_sha,
        "model_file":Path(config.model).name,"control_invoked":False,
        "warmth":"new Python provider; existing OLS/server/OS caches not reset",
        "scope":"read-only initialization and OLS; not P01-P11 end-to-end"}
    root=Path(__file__).resolve().parents[1]
    for name,path in (("brain",root),("control",Path(config.execution_control_root)),
                      ("ols",Path(config.asset_library_root).parent),("gateway",root.parent/"web-frontend-master")):
        environment[name+"_sha"]=subprocess.check_output(["git","-C",str(path),"rev-parse","HEAD"],text=True).strip()
    with trace_scope("preflight",output_dir=args.output) as trace:
        with span("startup.provider",source="scripts/perf_preflight.py:main"):
            provider=QwenHTTPProvider(config.base_url,config.model,atomic_skill_prompt_path=skill)
        assert provider.atomic_skill_source_sha256==skill_sha
        environment["skill_prompt_chars"]=len(provider.atomic_skill_prompt)
        environment["skill_prompt_bytes"]=len(provider.atomic_skill_prompt.encode("utf-8"))
        with span("startup.assets",source="scripts/perf_preflight.py:main"):
            assets=config.load_assets()
        with httpx.Client(timeout=30,trust_env=False) as client:
            environment["ols_parity"]=check_ols(client,args.ols_url,config.asset_library_root)
        for _ in range(5):
            assets.refresh_from_source()
        environment["qwen_http_calls"]=len(provider.calls)
    environment["trace_file"]=str(trace.path.relative_to(args.output)) if trace.path else None
    environment["trace_write_error"]=trace.output_error
    (args.output/"environment.json").write_text(json.dumps(environment,ensure_ascii=False,indent=2)+"\n")
    write_outputs(trace.records,args.output)
    print(args.output)


if __name__=="__main__":
    main()
