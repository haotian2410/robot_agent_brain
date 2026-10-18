"""Real Qwen, real scene metadata, demo-only interfaces; NEVER dispatch Control."""
import argparse
import json
from pathlib import Path
import uuid

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.robot_profile import RobotProfileRegistry
from robot_agent_brain.contracts.scene import SceneConfig


def verify_report(report, app, case):
    """Assert actual artifact contents, never just the success status."""
    from robot_agent_brain.contracts.commands_v3 import CommandsFileV3
    from robot_agent_brain.scene.component_access import SceneIndex
    from robot_agent_brain.planning.coordinated_validator import CoordinatedValidator
    assert report.run_status == "success" and report.executed is False
    commands = CommandsFileV3.model_validate_json(Path(report.artifacts["commands"]).read_text())
    scene = SceneConfig.model_validate_json(Path(report.artifacts["scene_config"]).read_text())
    index = SceneIndex(scene)
    assert commands.scene_id == scene.scene_id and commands.scene_version == scene.scene_version
    session = app.sessions[report.session_id]
    CoordinatedValidator().validate(commands, session.arm_states)
    actors = {side: {c.parameters.target for step in commands.steps
                    if (c := getattr(step.arms, side)) is not None and c.skill_name == "grasp"}
              for side in ("left", "right")}
    assert all(actors.values()) and not actors["left"].intersection(actors["right"])
    assert report.metrics["understanding_calls"] == report.metrics["skill_planning_calls"] == 1
    baseline = Path(report.artifacts["scene_config"]).parent.parent / "original_scene.json"
    assert SceneConfig.model_validate_json(baseline.read_text()) == scene
    if case in (1, 2):
        assert any(s.arms.left is not None and s.arms.right is not None for s in commands.steps)
        assert {index.semantic(i).semantic_name for i in actors["left"]} == {"apple"}
        assert {index.semantic(i).semantic_name for i in actors["right"]} == {"banana"}
    if case == 3:
        assert len(actors["left"] | actors["right"]) == 2
        assert sum(index.semantic(o.object_id_in_scene).semantic_name == "apple" for o in index.semantic_objects()) == 2
    if case == 4:
        assert commands.hold_constraints and commands.hold_constraints[0].kind == "hold_until_operation"
        held_stages = [s for s in commands.steps if s.arms.right is not None]
        assert all(s.arms.left is None and {c.predicate for c in s.invariants} >= {"holding", "at_region"} for s in held_stages)
    return {"artifact_assertions_passed": True, "case": case, "executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--output-dir", default="var/dual-arm-qwen-demo")
    parser.add_argument("--case", type=int, choices=[1, 2, 3, 4], help="Run only this case; omitted runs all")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    template = SceneConfig.model_validate_json((root / "model/final_models/scenes/5/cobotmagic_table_grasp.json").read_text())
    profiles = RobotProfileRegistry.model_validate({"default_dual": "brain_only_demo", "profiles": {"brain_only_demo": {
        "setup": {"mode": "dual", "profile_id": "brain_only_demo", "arms": {
            side: {"robot_object_id": identifier, "planning_group": f"DEMO_ONLY_{side}",
                   "end_effector": "DEMO_ONLY_tool", "gripper": "DEMO_ONLY_gripper"}
            for side, identifier in (("left", 2), ("right", 3))}},
        "template": template, "robot_object_ids": [2, 3, 4, 6], "platform_object_ids": list(range(7)),
        "platform_roles": {"table": 1, "ambient": 0, "overhead_camera": 5},
        "supported_skills": ["locate", "move", "grasp", "release"], "commands_version": "3.0",
        "coordinated_execution": True, "default_task_arm": "left",
        "initial_state": {"arms": {side: {"state_known": True} for side in ("left", "right")}}
    }}})
    config = BrainConfig.load(root / "config/final_models.json", overrides={
        "model": args.model, "base_url": args.base_url, "output_dir": str(Path(args.output_dir).resolve()),
        "debug": True, "planner": "qwen", "planner_max_completion_tokens": 4096,
        "robot_profiles": profiles.model_dump(), "timeout": 180})
    app = BrainApplication(config)
    instructions = [
        "用双臂，左臂抓住一个苹果，同时右臂抓住一个香蕉",
        "用双臂，左臂把一个苹果放进一个蓝色篮子里，同时右臂把一个香蕉向右移动十厘米",
        "用双臂分别抓两个苹果，两只手各抓一个苹果",
        "用双臂，左臂把一个苹果移到一个蓝色篮子的放置区域，先不要松手；左臂保持位置，右臂把一个香蕉右移十厘米并放下，然后左臂再松手",
    ]
    run = uuid.uuid4().hex[:10]
    reports = []
    for i, instruction in enumerate(instructions, 1):
        if args.case is not None and args.case != i:
            continue
        report = app.handle(instruction, session_id=f"dual-{run}-{i}")
        reports.append(report.model_dump(mode="json"))
        try:
            reports[-1]["verification"] = verify_report(report, app, i)
        except Exception as exc:
            reports[-1]["verification"] = {"artifact_assertions_passed": False, "error": str(exc)}
        print(json.dumps({"demo_only_no_dispatch": True, **reports[-1]}, ensure_ascii=False), flush=True)
    summary = {"real_qwen": True, "physical_execution": False,
               "interfaces": "DEMO_ONLY placeholders, not Control registrations", "reports": reports}
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / f"summary-{run}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(any(r["run_status"] != "success" or not r["verification"]["artifact_assertions_passed"] for r in reports))


if __name__ == "__main__":
    raise SystemExit(main())
