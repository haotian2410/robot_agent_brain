"""Real Qwen asset integration checks; only export data, never execute robots."""
import argparse
import json
from pathlib import Path
import uuid

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ("automatic", None, "把苹果放进蓝色篮子"),
    ("sorting", "3/ur5e_table_sorting.json", "把香蕉放进篮子"),
    ("edit", "1/ur5e_table_empty.json", "在桌子右边增加一个香蕉"),
    ("cabinet", "4/ur5e_table_cabinet.json", "柜子有几个"),
    ("drawer", None, "增加一个抽屉"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "var/final-models-demo")
    args = parser.parse_args()
    options = dict(provider="qwen", planner="qwen", base_url=args.base_url,
                   debug=True, output_dir=str(args.output_dir.resolve()))
    if args.model:
        options["model"] = args.model
    config = BrainConfig.load(ROOT / "config/final_models.json", overrides=options)
    results = []
    for name, scene, instruction in CASES:
        app = BrainApplication(config)
        path = ROOT / "model/final_models/scenes" / scene if scene else None
        report = app.handle(instruction, session_id=f"{name}-{uuid.uuid4().hex[:12]}", scene_path=path)
        results.append({"case": name, "instruction": instruction, **report.model_dump(mode="json")})
        print(f"{name}: {report.run_status} — {report.reply}", flush=True)
    output = args.output_dir.resolve() / "demo_summary.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
