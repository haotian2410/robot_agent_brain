"""Real Qwen multi-turn scale/color checks. Never execute robot commands."""
import argparse
import json
from pathlib import Path
import uuid

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Qwen3.8-27B")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "var/scale-color-demo")
    args = parser.parse_args()
    config = BrainConfig.load(ROOT / "config/final_models.json", overrides={
        "provider": "qwen", "planner": "qwen", "model": args.model, "base_url": args.base_url,
        "output_dir": str(args.output_dir.resolve()), "debug": True})
    app = BrainApplication(config)
    session = "scale-color-" + uuid.uuid4().hex[:12]
    cases = [
        ("把苹果放进蓝色篮子", "success", None),
        ("把蓝色篮子放大一点", "success", None),
        ("把篮子的XYZ缩放设为1.2、1.1、1.1", "success", None),
        ("把苹果放大一点", "blocked", "scene_scale_forbidden"),
        ("把苹果改成蓝色", "success", None),
        ("蓝色苹果有几个", "success", None),
        ("把蓝色苹果放进篮子", "success", None),
        ("把篮子右移2厘米，再放大一点，再改成蓝色", "success", None),
        ("把苹果改成红色，再把苹果放大一点", "blocked", "scene_scale_forbidden"),
        ("把篮子的XYZ缩放设为100、100、100", "blocked", "scene_scale_out_of_range"),
    ]
    cases = [(session, *case) for case in cases] + [
        (session + "-multi", "在场景中增加两个蓝色篮子", "success", None),
        (session + "-multi", "把两个蓝色篮子都放大一点", "success", None),
        (session + "-multi", "把两个篮子都改成红色", "success", None),
    ]
    reports, errors = [], []
    for current_session, instruction, expected, code in cases:
        state = app.get_session(current_session).scene
        before = state.model_dump(mode="json") if state else None
        report = app.handle(instruction, session_id=current_session)
        after = app.get_session(current_session).scene
        checks = []
        if report.run_status != expected:
            checks.append(f"expected {expected}, got {report.run_status}")
        if code and (report.error is None or report.error.code != code):
            checks.append(f"expected error {code}")
        if expected == "blocked" and before != (after.model_dump(mode="json") if after else None):
            checks.append("blocked turn changed scene")
        if report.executed:
            checks.append("Brain must never execute")
        if report.turn_kind == "scene_edit" and "commands" in report.artifacts:
            checks.append("scene edit exported robot commands")
        if report.turn_kind == "scene_query" and report.run_status == "success":
            result = json.loads(Path(report.artifacts["query_result"]).read_text())
            if result["count"] != 1:
                checks.append("expected one blue apple")
        if current_session.endswith("-multi") and report.run_status == "success":
            from robot_agent_brain.scene.component_access import SceneIndex
            index = SceneIndex(after)
            baskets = [o for o in index.semantic_objects() if index.semantic(o.object_id_in_scene).semantic_name == "basket"]
            if len(baskets) != 2:
                checks.append("expected two basket instances")
            if "放大" in instruction and any(index.transform(o.object_id_in_scene).scale != (1.1,)*3 for o in baskets):
                checks.append("not all baskets scaled")
            if "红色" in instruction and any(index.component(o.object_id_in_scene,"MeshRenderer").properties["forceOverrideColor"] != "#FF0000" for o in baskets):
                checks.append("not all baskets recolored")
        reports.append({"instruction": instruction, "checks": checks, **report.model_dump(mode="json")})
        errors.extend(checks)
        print(f"{report.run_status}: {instruction} — {report.reply} {checks}", flush=True)
    summary = args.output_dir.resolve() / "scale_color_summary.json"
    summary.write_text(json.dumps({"passed": not errors, "errors": errors, "reports": reports},
                                  ensure_ascii=False, indent=2) + "\n")
    print(summary)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
