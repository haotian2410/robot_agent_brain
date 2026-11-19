#!/usr/bin/env python3
"""Create isolated diagnostic configs; never modify production configuration."""
import argparse
import json
from pathlib import Path
from robot_agent_brain.config import BrainConfig


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain-config",required=True,type=Path)
    parser.add_argument("--gateway-config",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--brain-port",type=int,default=8503)
    parser.add_argument("--gateway-port",type=int,default=8096)
    args=parser.parse_args()
    root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    config=BrainConfig.load(args.brain_config)
    if config.planner!="qwen" or config.control_skill_prompt_path() is None:
        raise SystemExit("requires_qwen_and_control_skill_prompt")
    data=config.model_dump(mode="json")
    data.update(output_dir=str(root/"tasks"),execution_enabled=False,
                execution_workspace_root=str(root/"control-requests"),
                control_skill_prompt=config.control_skill_prompt_path())
    (root/"brain.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    gateway=json.loads(args.gateway_config.read_text())
    gateway["gateway"]={"host":"127.0.0.1","port":args.gateway_port}
    gateway["agent_service_url"]=f"http://127.0.0.1:{args.brain_port}"
    (root/"gateway.json").write_text(json.dumps(gateway,ensure_ascii=False,indent=2)+"\n")
    print(root)


if __name__=="__main__":
    main()
